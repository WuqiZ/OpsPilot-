import json
import pathlib
import unittest
from types import SimpleNamespace

from agents.agent_orchestrator import AgentOrchestrator, AgentType, Request
from core.intent_recognizer import IntentCategory, IntentRecognizer, IntentResult, UrgencyLevel
from core.llm_utils import llm_request_options, parse_json_object, require_text_content
from core.skill_loader import SkillManager
from evaluation.cases import load_evaluation_dataset
from evaluation.evaluator import EndToEndEvaluator, EvalResult, LLMJudge
from rag.retriever import RAGRetriever


class FakeMessages:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    async def create(self, **_):
        output = self.outputs.pop(0)
        return SimpleNamespace(content=[{"type": "text", "text": output}])


class FakeClient:
    def __init__(self, *outputs):
        self.messages = FakeMessages(outputs)


class StubRecognizer:
    def __init__(self, result):
        self.result = result

    async def recognize(self, *_):
        return self.result


class FakeKnowledgeBase:
    async def search(self, query, top_k=5, source="all"):
        return [
            {"title": "VPN SOP", "content": "check gateway", "source": "knowledge", "score": 0.7},
            {"title": f"case {query}", "content": f"evidence {query}", "source": "incident", "score": 0.6},
        ][:top_k]


class IntentRecognizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_fuses_intent_and_extracts_entities(self):
        client = FakeClient(json.dumps({
            "intent": "identity_access",
            "confidence": 0.96,
            "urgency": "medium",
            "reasoning": "403 permission failure",
            "entities": {"error_code": ["403"]},
        }))
        recognizer = IntentRecognizer("test", client=client, use_model_embeddings=False)

        result = await recognizer.recognize("账号 user@example.com 登录提示 403")

        self.assertEqual(result.intent, IntentCategory.IDENTITY_ACCESS)
        self.assertGreaterEqual(result.confidence, 0.55)
        self.assertIn("403", result.entities["error_code"])
        self.assertFalse(result.needs_clarification)

    async def test_low_confidence_requests_clarification(self):
        client = FakeClient(json.dumps({
            "intent": "other",
            "confidence": 0.2,
            "urgency": "low",
            "reasoning": "insufficient detail",
            "entities": {},
        }))
        recognizer = IntentRecognizer("test", client=client, use_model_embeddings=False)

        result = await recognizer.recognize("帮我看一下")

        self.assertTrue(result.needs_clarification)
        self.assertIn("网络", result.clarification_question)

    async def test_security_signal_is_not_blocked_by_low_confidence(self):
        client = FakeClient(json.dumps({
            "intent": "security",
            "confidence": 0.3,
            "urgency": "high",
            "reasoning": "possible phishing",
            "entities": {},
        }))
        recognizer = IntentRecognizer("test", client=client, use_model_embeddings=False)

        result = await recognizer.recognize("我可能误点了钓鱼邮件")

        self.assertEqual(result.intent, IntentCategory.SECURITY)
        self.assertLess(result.confidence, 0.55)
        self.assertFalse(result.needs_clarification)

    def test_entity_and_urgency_rules(self):
        recognizer = IntentRecognizer("test", client=FakeClient(), use_model_embeddings=False)

        entities = recognizer._extract_local_entities("账号出现异常登录，VPN 三个人受影响")
        merged = recognizer._merge_entities(entities, {"software": ["VPN"]})

        self.assertNotIn("account", entities)
        self.assertNotIn("software", merged)
        self.assertEqual(len(merged["network_service"]), 1)
        self.assertEqual({value.lower() for value in merged["network_service"]}, {"vpn"})
        self.assertEqual(
            recognizer._resolve_urgency("VPN 三个人受影响", IntentCategory.NETWORK, None),
            UrgencyLevel.HIGH,
        )


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def test_dynamic_route_selects_primary_and_secondary(self):
        client = FakeClient()
        orchestrator = AgentOrchestrator("test", client=client)
        request = Request(
            message="VPN 可以连接但登录提示 401",
            intent=IntentCategory.NETWORK,
            urgency=UrgencyLevel.LOW,
            intent_confidence=0.9,
        )

        decision = orchestrator.route(request)

        self.assertEqual(decision.primary, AgentType.NETWORK)
        self.assertEqual(decision.secondary, [AgentType.IDENTITY_ACCESS])
        self.assertIn("主 Agent=network", decision.reason)

    async def test_run_returns_observable_agent_trace(self):
        intent = IntentResult(
            intent=IntentCategory.SOFTWARE,
            confidence=0.91,
            urgency=UrgencyLevel.LOW,
            entities={"software": ["Office"]},
            reasoning="software crash",
            needs_clarification=False,
            clarification_question=None,
        )
        client = FakeClient("请检查事件日志，并在修复后重新启动 Office 验证。")
        orchestrator = AgentOrchestrator(
            "test",
            client=client,
            recognizer=StubRecognizer(intent),
        )

        result = await orchestrator.run(Request(message="Office 启动后崩溃"))

        self.assertEqual(result.agent_type, AgentType.SOFTWARE)
        self.assertEqual(result.agent_trace[1]["stage"], "routing")
        self.assertEqual(result.agent_trace[-1]["status"], "success")

    async def test_clarification_stops_agent_execution(self):
        intent = IntentResult(
            intent=IntentCategory.OTHER,
            confidence=0.1,
            urgency=UrgencyLevel.LOW,
            entities={},
            reasoning="ambiguous",
            needs_clarification=True,
            clarification_question="请补充具体故障现象。",
        )
        orchestrator = AgentOrchestrator(
            "test",
            client=FakeClient(),
            recognizer=StubRecognizer(intent),
        )

        result = await orchestrator.run(Request(message="有问题"))

        self.assertTrue(result.clarification_required)
        self.assertEqual(result.agent_trace[-1]["status"], "clarify")


class RetrieverTests(unittest.IsolatedAsyncioTestCase):
    async def test_rewrite_parallel_recall_dedupe_and_rerank(self):
        client = FakeClient(
            '["VPN authentication", "VPN gateway", "LDAP dependency"]',
            "[2, 0, 1, 3]",
        )
        retriever = RAGRetriever(FakeKnowledgeBase(), "test", client=client)

        result = await retriever.retrieve("VPN 登录失败", top_k=2)

        self.assertEqual(result.rewritten_queries[0], "VPN 登录失败")
        self.assertEqual(len(result.items), 2)
        self.assertTrue(result.reranked)


class SkillTests(unittest.TestCase):
    def test_domain_skills_are_loaded_and_scoped(self):
        manager = SkillManager("skills")
        manager.load()

        self.assertEqual(len(manager.skills), 5)
        self.assertIn("Identity and access", manager.prompt_for("登录提示 403", "identity_access"))
        self.assertEqual(manager.prompt_for("登录提示 403", "device"), "")


class LLMUtilsTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_markdown_wrapped_json(self):
        value = parse_json_object('result:\n```json\n{"ok": true}\n```')
        self.assertEqual(value, {"ok": True})

    def test_thinking_only_response_is_not_treated_as_final_answer(self):
        with self.assertRaisesRegex(ValueError, "no final text"):
            require_text_content([{"type": "thinking", "thinking": "internal"}], "test")

    def test_deepseek_disables_thinking_by_default(self):
        options = llm_request_options("https://api.deepseek.com/anthropic")
        self.assertEqual(options["extra_body"]["thinking"], {"type": "disabled"})
        self.assertEqual(options["extra_body"]["output_config"], {"effort": "low"})

    async def test_judge_parses_json_response(self):
        client = FakeClient(
            '```json\n{"relevance":0.9,"accuracy":0.8,"completeness":0.7,"actionability":1.0}\n```'
        )
        scores = await LLMJudge(client, "test").judge("question", "answer")

        self.assertFalse(scores.judge_failed)
        self.assertAlmostEqual(scores.overall, 0.85)


class EvaluationDatasetTests(unittest.TestCase):
    def test_committed_dataset_has_200_unique_stratified_cases(self):
        path = pathlib.Path(__file__).parents[1] / "evaluation" / "datasets" / "opspilot_eval_200.json"

        dataset = load_evaluation_dataset(path)

        self.assertEqual(dataset.total, 200)
        self.assertEqual(dataset.breakdown, {
            "intent": 100,
            "routing": 50,
            "retrieval": 25,
            "dialog": 25,
        })
        self.assertEqual(dataset.provenance, "expert_curated_synthetic_offline_regression")

    def test_macro_f1_binary_metrics_and_percentile(self):
        pairs = [("a", "a"), ("a", "b"), ("b", "b")]

        self.assertAlmostEqual(EndToEndEvaluator._macro_f1(pairs), 2 / 3)
        self.assertEqual(
            EndToEndEvaluator._binary_metrics([(True, True), (True, False), (False, True)]),
            (0.5, 0.5, 0.5),
        )
        self.assertAlmostEqual(EndToEndEvaluator._percentile([1.0, 2.0, 3.0, 4.0], 0.95), 3.85)

    def test_secondary_agent_metrics_penalize_extra_and_missing_agents(self):
        results = [
            EvalResult(
                "routing_0",
                True,
                {},
                "",
                {"expected_secondary": ["software"], "actual_secondary": ["software"]},
            ),
            EvalResult(
                "routing_1",
                False,
                {},
                "",
                {"expected_secondary": ["device"], "actual_secondary": ["security"]},
            ),
        ]

        metrics = EndToEndEvaluator._routing_metrics(results)

        self.assertEqual(metrics["secondary_agent_precision"], 0.5)
        self.assertEqual(metrics["secondary_agent_recall"], 0.5)
        self.assertEqual(metrics["secondary_agent_f1"], 0.5)


if __name__ == "__main__":
    unittest.main()
