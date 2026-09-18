"""Reproducible evaluation for intent, routing, retrieval and end-to-end diagnosis."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, TypeVar

from anthropic import AsyncAnthropic

from agents.agent_orchestrator import AgentOrchestrator, Request
from core.intent_recognizer import IntentCategory, UrgencyLevel
from core.llm_utils import llm_request_options, parse_json_object, require_text_content
from evaluation.cases import (
    DialogTestCase,
    IntentTestCase,
    RetrievalTestCase,
    RoutingTestCase,
    load_evaluation_dataset,
)
from rag.retriever import RAGRetriever


logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class EvalResult:
    test_id: str
    passed: bool
    scores: Dict[str, float]
    detail: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalReport:
    timestamp: str
    dataset_name: str
    dataset_version: str
    dataset_provenance: str
    breakdown: Dict[str, int]
    total: int
    passed: int
    pass_rate: float
    avg_scores: Dict[str, float]
    regressions: List[str]
    recommendations: List[str]
    results: List[EvalResult]


@dataclass
class QualityScores:
    relevance: float
    accuracy: float
    completeness: float
    actionability: float
    judge_failed: bool = False
    error: Optional[str] = None

    @property
    def overall(self) -> float:
        return statistics.mean([
            self.relevance,
            self.accuracy,
            self.completeness,
            self.actionability,
        ])


class LLMJudge:
    def __init__(self, client: Any, model: str, base_url: Optional[str] = None):
        self._client = client
        self._model = model
        self._message_options = llm_request_options(base_url)

    async def judge(self, question: str, answer: str) -> QualityScores:
        prompt = f"""Evaluate an enterprise IT diagnosis answer from 0.0 to 1.0.
Question: {self._clean(question)}
Answer: {self._clean(answer)}

Score relevance, technical accuracy, completeness and actionability.
Penalize invented system facts, unsafe destructive actions, missing verification steps,
and requests for passwords or secrets. Return JSON only:
{{"relevance":0.0,"accuracy":0.0,"completeness":0.0,"actionability":0.0}}"""
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=250,
                temperature=0.0,
                system="Return exactly one valid JSON object. Do not use Markdown or explanatory text.",
                messages=[{"role": "user", "content": prompt}],
                **self._message_options,
            )
            raw = require_text_content(response.content, "LLM judge")
            data = parse_json_object(raw)
            return QualityScores(*(
                self._score(data.get(key))
                for key in ["relevance", "accuracy", "completeness", "actionability"]
            ))
        except Exception as exc:
            logger.warning("LLM judge failed: %s: %s", type(exc).__name__, exc)
            return QualityScores(0.0, 0.0, 0.0, 0.0, judge_failed=True, error=type(exc).__name__)

    @staticmethod
    def _score(value: Any) -> float:
        try:
            return min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").encode("utf-8", errors="ignore").decode("utf-8")


class EndToEndEvaluator:
    PASS_THRESHOLD = 0.75

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        baseline_path: Optional[str] = None,
        dataset_path: Optional[str] = None,
        retriever: Optional[RAGRetriever] = None,
        client: Optional[Any] = None,
        concurrency: Optional[int] = None,
    ):
        if client is None:
            kwargs: Dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = AsyncAnthropic(**kwargs)
        self._orchestrator = orchestrator
        self._retriever = retriever
        self._judge = LLMJudge(client, model, base_url)
        self._baseline_path = pathlib.Path(baseline_path) if baseline_path else None
        self._dataset_path = pathlib.Path(dataset_path) if dataset_path else None
        self._concurrency = max(1, concurrency or int(os.getenv("EVAL_CONCURRENCY", "4")))
        self._baseline = self._load_baseline()

    async def run(
        self,
        intent_cases: Optional[List[IntentTestCase]] = None,
        routing_cases: Optional[List[RoutingTestCase]] = None,
        retrieval_cases: Optional[List[RetrievalTestCase]] = None,
        dialog_cases: Optional[List[DialogTestCase | str]] = None,
        full_dataset: bool = False,
    ) -> EvalReport:
        dataset_name = "opspilot_smoke"
        dataset_version = "1.0"
        dataset_provenance = "built_in_smoke_cases"
        if full_dataset:
            if self._dataset_path is None:
                raise ValueError("EVAL_DATASET_PATH is not configured")
            dataset = load_evaluation_dataset(self._dataset_path)
            intent_cases = dataset.intent_cases
            routing_cases = dataset.routing_cases
            retrieval_cases = dataset.retrieval_cases
            dialog_cases = dataset.dialog_cases
            dataset_name = dataset.name
            dataset_version = dataset.version
            dataset_provenance = dataset.provenance
        else:
            intent_cases = intent_cases if intent_cases is not None else DEFAULT_INTENT_CASES
            routing_cases = routing_cases if routing_cases is not None else DEFAULT_ROUTING_CASES
            retrieval_cases = retrieval_cases if retrieval_cases is not None else DEFAULT_RETRIEVAL_CASES
            dialog_cases = dialog_cases if dialog_cases is not None else DEFAULT_DIALOG_CASES

        normalized_dialogs = [
            case if isinstance(case, DialogTestCase) else DialogTestCase(question=case)
            for case in dialog_cases
        ]
        sections = {
            "intent": await self._map_cases(intent_cases, self._evaluate_intent),
            "routing": await self._map_cases(routing_cases, self._evaluate_routing),
            "retrieval": await self._map_cases(retrieval_cases, self._evaluate_retrieval),
            "dialog": await self._map_cases(normalized_dialogs, self._evaluate_dialog),
        }
        results = [result for section in sections.values() for result in section]
        averages = self._average_scores(results)
        averages.update(self._classification_metrics(sections["intent"]))
        averages.update(self._routing_metrics(sections["routing"]))
        averages.update(self._latency_metrics(sections["dialog"]))
        passed = sum(result.passed for result in results)
        report = EvalReport(
            timestamp=datetime.now().astimezone().isoformat(),
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            dataset_provenance=dataset_provenance,
            breakdown={name: len(values) for name, values in sections.items()},
            total=len(results),
            passed=passed,
            pass_rate=round(passed / max(1, len(results)), 4),
            avg_scores=averages,
            regressions=self._detect_regressions(averages, dataset_name),
            recommendations=self._recommendations(averages),
            results=results,
        )
        self._save_baseline(report)
        return report

    async def _map_cases(
        self,
        cases: Sequence[T],
        evaluator: Callable[[int, T], Awaitable[EvalResult]],
    ) -> List[EvalResult]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def guarded(index: int, case: T) -> EvalResult:
            async with semaphore:
                try:
                    return await evaluator(index, case)
                except Exception as exc:
                    logger.exception("Evaluation case failed: %s_%s", evaluator.__name__, index)
                    prefix = evaluator.__name__.removeprefix("_evaluate_")
                    return EvalResult(
                        test_id=f"{prefix}_{index}",
                        passed=False,
                        scores={f"{prefix}_execution_success": 0.0},
                        detail=f"evaluation_error={type(exc).__name__}",
                        metadata={"error": type(exc).__name__, "message": str(exc)[:300]},
                    )

        return list(await asyncio.gather(*(
            guarded(index, case) for index, case in enumerate(cases)
        )))

    async def _evaluate_intent(self, index: int, case: IntentTestCase) -> EvalResult:
        prediction = await self._orchestrator.classify(Request(message=case.message))
        intent_correct = prediction.intent.value == case.expected_intent
        clarification_correct = prediction.needs_clarification == case.expect_clarification
        return EvalResult(
            test_id=f"intent_{index}",
            passed=intent_correct and clarification_correct,
            scores={
                "intent_accuracy": float(intent_correct),
                "clarification_accuracy": float(clarification_correct),
            },
            detail=(
                f"expected={case.expected_intent}, predicted={prediction.intent.value}, "
                f"confidence={prediction.confidence:.3f}"
            ),
            metadata={
                "expected_intent": case.expected_intent,
                "predicted_intent": prediction.intent.value,
                "expected_clarification": case.expect_clarification,
                "predicted_clarification": prediction.needs_clarification,
                "entities": prediction.entities,
                "urgency": prediction.urgency.value,
            },
        )

    async def _evaluate_routing(self, index: int, case: RoutingTestCase) -> EvalResult:
        request = Request(
            message=case.message,
            intent=IntentCategory(case.intent),
            urgency=UrgencyLevel.LOW,
            entities=case.entities,
            intent_confidence=1.0,
        )
        decision = self._orchestrator.route(request)
        actual_secondary = [agent.value for agent in decision.secondary]
        primary_correct = decision.primary.value == case.expected_primary
        secondary_exact = set(actual_secondary) == set(case.expected_secondary)
        passed = primary_correct and secondary_exact
        return EvalResult(
            test_id=f"routing_{index}",
            passed=passed,
            scores={
                "routing_primary_accuracy": float(primary_correct),
                "routing_exact_match": float(passed),
            },
            detail=(
                f"expected={case.expected_primary}/{case.expected_secondary}, "
                f"actual={decision.primary.value}/{actual_secondary}"
            ),
            metadata={
                "expected_primary": case.expected_primary,
                "actual_primary": decision.primary.value,
                "expected_secondary": case.expected_secondary,
                "actual_secondary": actual_secondary,
                "scores": decision.scores,
                "reason": decision.reason,
            },
        )

    async def _evaluate_retrieval(self, index: int, case: RetrievalTestCase) -> EvalResult:
        if self._retriever is None:
            raise RuntimeError("retriever is not configured")
        retrieval = await self._retriever.retrieve(case.query, top_k=case.top_k)
        titles = [str(item.get("title", "")) for item in retrieval.items]
        expected = set(case.expected_titles)
        hits = expected.intersection(titles)
        recall = len(hits) / max(1, len(expected))
        first_rank = next((rank for rank, title in enumerate(titles, start=1) if title in expected), None)
        reciprocal_rank = 1.0 / first_rank if first_rank else 0.0
        return EvalResult(
            test_id=f"retrieval_{index}",
            passed=recall == 1.0,
            scores={"rag_recall_at_4": recall, "rag_mrr": reciprocal_rank},
            detail=f"expected={case.expected_titles}, retrieved={titles}",
            metadata={
                "query": case.query,
                "expected_titles": case.expected_titles,
                "retrieved_titles": titles,
                "rewritten_queries": retrieval.rewritten_queries,
                "reranked": retrieval.reranked,
            },
        )

    async def _evaluate_dialog(self, index: int, case: DialogTestCase) -> EvalResult:
        started = time.monotonic()
        request = Request(message=case.question)
        intent = await self._orchestrator.classify(request)
        retrieval = None
        if not intent.needs_clarification and self._retriever is not None:
            retrieval = await self._retriever.retrieve(case.question, top_k=4)
            request.context = self._build_retrieval_context(retrieval.items)
        result = await self._orchestrator.run(request, intent_result=intent)
        quality = await self._judge.judge(case.question, result.response)
        primary_correct = case.expected_primary is None or result.agent_type.value == case.expected_primary
        execution_steps = [
            step for step in result.agent_trace if step.get("stage") in {"agent_execution", "fallback"}
        ]
        execution_success = any(step.get("status") == "success" for step in execution_steps)
        passed = (
            not quality.judge_failed
            and quality.overall >= case.min_overall
            and primary_correct
            and execution_success
            and not result.clarification_required
        )
        latency_ms = (time.monotonic() - started) * 1000
        return EvalResult(
            test_id=f"dialog_{index}",
            passed=passed,
            scores={
                "relevance": quality.relevance,
                "accuracy": quality.accuracy,
                "completeness": quality.completeness,
                "actionability": quality.actionability,
                "end_to_end_quality": quality.overall,
                "dialog_primary_accuracy": float(primary_correct),
                "agent_execution_success": float(execution_success),
                "judge_success": float(not quality.judge_failed),
            },
            detail=f"overall={quality.overall:.3f}, primary={result.agent_type.value}",
            metadata={
                "question": case.question,
                "response": result.response,
                "expected_primary": case.expected_primary,
                "primary_agent": result.agent_type.value,
                "routing_reason": result.routing_reason,
                "clarification_required": result.clarification_required,
                "knowledge_used": bool(retrieval and retrieval.items),
                "retrieved_titles": [item.get("title", "") for item in retrieval.items] if retrieval else [],
                "judge_failed": quality.judge_failed,
                "judge_error": quality.error,
                "latency_ms": round(latency_ms, 1),
            },
        )

    @staticmethod
    def _build_retrieval_context(evidence: List[Dict[str, Any]]) -> str:
        if not evidence:
            return ""
        lines = [
            f"{index}. [{item.get('source', '')}] {item.get('title', '')}\n{item.get('content', '')}"
            for index, item in enumerate(evidence, start=1)
        ]
        return "[Retrieved evidence]\n" + "\n".join(lines)

    @staticmethod
    def _average_scores(results: List[EvalResult]) -> Dict[str, float]:
        grouped: Dict[str, List[float]] = {}
        for result in results:
            for name, score in result.scores.items():
                grouped.setdefault(name, []).append(score)
        return {name: round(statistics.mean(values), 4) for name, values in grouped.items()}

    @classmethod
    def _classification_metrics(cls, results: List[EvalResult]) -> Dict[str, float]:
        pairs = [
            (result.metadata.get("expected_intent"), result.metadata.get("predicted_intent"))
            for result in results
            if result.metadata.get("expected_intent") is not None
        ]
        macro_f1 = cls._macro_f1(pairs)
        clarification_pairs = [
            (
                bool(result.metadata.get("expected_clarification")),
                bool(result.metadata.get("predicted_clarification")),
            )
            for result in results
            if "expected_clarification" in result.metadata
        ]
        precision, recall, f1 = cls._binary_metrics(clarification_pairs)
        return {
            "intent_macro_f1": round(macro_f1, 4),
            "clarification_precision": round(precision, 4),
            "clarification_recall": round(recall, 4),
            "clarification_f1": round(f1, 4),
        }

    @classmethod
    def _routing_metrics(cls, results: List[EvalResult]) -> Dict[str, float]:
        true_positive = false_positive = false_negative = 0
        for result in results:
            if "expected_secondary" not in result.metadata:
                continue
            expected = set(result.metadata["expected_secondary"])
            actual = set(result.metadata["actual_secondary"])
            true_positive += len(expected & actual)
            false_positive += len(actual - expected)
            false_negative += len(expected - actual)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "secondary_agent_precision": round(precision, 4),
            "secondary_agent_recall": round(recall, 4),
            "secondary_agent_f1": round(f1, 4),
        }

    @staticmethod
    def _latency_metrics(results: List[EvalResult]) -> Dict[str, float]:
        values = sorted(
            float(result.metadata["latency_ms"])
            for result in results
            if result.metadata.get("latency_ms") is not None
        )
        if not values:
            return {}
        return {
            "latency_p50_ms": round(EndToEndEvaluator._percentile(values, 0.50), 1),
            "latency_p95_ms": round(EndToEndEvaluator._percentile(values, 0.95), 1),
        }

    @staticmethod
    def _macro_f1(pairs: Sequence[tuple[Any, Any]]) -> float:
        if not pairs:
            return 0.0
        labels = sorted({label for pair in pairs for label in pair if label is not None})
        values = []
        for label in labels:
            true_positive = sum(expected == label and predicted == label for expected, predicted in pairs)
            false_positive = sum(expected != label and predicted == label for expected, predicted in pairs)
            false_negative = sum(expected == label and predicted != label for expected, predicted in pairs)
            precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
            recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
            values.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
        return statistics.mean(values)

    @staticmethod
    def _binary_metrics(pairs: Sequence[tuple[bool, bool]]) -> tuple[float, float, float]:
        true_positive = sum(expected and predicted for expected, predicted in pairs)
        false_positive = sum(not expected and predicted for expected, predicted in pairs)
        false_negative = sum(expected and not predicted for expected, predicted in pairs)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return precision, recall, f1

    @staticmethod
    def _percentile(values: Sequence[float], quantile: float) -> float:
        if len(values) == 1:
            return values[0]
        position = (len(values) - 1) * quantile
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        weight = position - lower
        return values[lower] * (1 - weight) + values[upper] * weight

    def _detect_regressions(self, current: Dict[str, float], dataset_name: str) -> List[str]:
        if self._baseline is None or self._baseline.dataset_name != dataset_name:
            return []
        regressions = []
        for metric, value in current.items():
            previous = self._baseline.avg_scores.get(metric)
            if previous and (value - previous) / previous < -0.05:
                regressions.append(f"{metric}: {previous:.3f} -> {value:.3f}")
        return regressions

    @staticmethod
    def _recommendations(scores: Dict[str, float]) -> List[str]:
        recommendations = []
        if scores.get("intent_macro_f1", 1.0) < 0.90:
            recommendations.append("补充低 F1 类别的 Few-shot 和关键词样本。")
        if scores.get("clarification_f1", 1.0) < 0.90:
            recommendations.append("校准融合置信度阈值和澄清问题。")
        if scores.get("routing_exact_match", 1.0) < 0.90:
            recommendations.append("调整实体、关键词和上下文的路由评分权重。")
        if scores.get("rag_recall_at_4", 1.0) < 0.90:
            recommendations.append("扩充知识语料并优化 Query Rewrite 与 Rerank。")
        if scores.get("actionability", 1.0) < 0.75:
            recommendations.append("在 SOP 中补充可验证的诊断步骤。")
        return recommendations or ["核心指标达标，下一步使用脱敏真实工单做外部验证。"]

    def _load_baseline(self) -> Optional[EvalReport]:
        if self._baseline_path is None or not self._baseline_path.exists():
            return None
        try:
            data = json.loads(self._baseline_path.read_text(encoding="utf-8"))
            return EvalReport(
                timestamp=data.get("timestamp", ""),
                dataset_name=data.get("dataset_name", "legacy"),
                dataset_version=data.get("dataset_version", "1.0"),
                dataset_provenance=data.get("dataset_provenance", "unspecified"),
                breakdown=dict(data.get("breakdown", {})),
                total=int(data.get("total", 0)),
                passed=int(data.get("passed", 0)),
                pass_rate=float(data.get("pass_rate", 0.0)),
                avg_scores=dict(data.get("avg_scores", {})),
                regressions=list(data.get("regressions", [])),
                recommendations=list(data.get("recommendations", [])),
                results=[],
            )
        except Exception:
            return None

    def _save_baseline(self, report: EvalReport) -> None:
        if self._baseline_path is None:
            return
        self._baseline_path.parent.mkdir(parents=True, exist_ok=True)
        self._baseline_path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._baseline = report


DEFAULT_INTENT_CASES = [
    IntentTestCase("公司 VPN 一直超时，无法访问内网", "network"),
    IntentTestCase("账号登录提示 403，没有项目权限", "identity_access"),
    IntentTestCase("Office 升级后启动就崩溃", "software"),
    IntentTestCase("办公区打印机显示离线", "device"),
    IntentTestCase("我误点了钓鱼邮件，账号出现异常登录", "security"),
    IntentTestCase("帮我看一下", "other", expect_clarification=True),
]


DEFAULT_ROUTING_CASES = [
    RoutingTestCase("VPN 连接超时", "network", "network"),
    RoutingTestCase("登录 401", "identity_access", "identity_access"),
    RoutingTestCase(
        "VPN 可以连接但登录提示 401",
        "network",
        "network",
        expected_secondary=["identity_access"],
    ),
    RoutingTestCase("打印机驱动升级后设备离线", "device", "device", expected_secondary=["software"]),
]


DEFAULT_RETRIEVAL_CASES = [
    RetrievalTestCase("多人 VPN 认证失败", ["VPN 连接故障排查 SOP", "历史案例：VPN 全员认证失败"]),
    RetrievalTestCase("403 项目权限不足", ["账号权限故障排查 SOP"]),
]


DEFAULT_DIALOG_CASES = [
    DialogTestCase("公司 VPN 从今天早上开始连接超时，三个人受影响", "network"),
    DialogTestCase("账号登录提示 403，但同事可以访问同一个系统", "identity_access"),
    DialogTestCase("笔记本升级后蓝屏，错误码 0x0000007E", "device"),
    DialogTestCase("我刚点击了可疑邮件中的链接，应该怎么处理", "security"),
]
