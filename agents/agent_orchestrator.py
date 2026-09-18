"""Multi-agent routing and collaboration for OpsPilot IT diagnosis."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from core.intent_recognizer import IntentCategory, IntentRecognizer, IntentResult, UrgencyLevel
from core.llm_utils import llm_request_options, require_text_content


logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    TRIAGE = "triage"
    NETWORK = "network"
    IDENTITY_ACCESS = "identity_access"
    SOFTWARE = "software"
    DEVICE = "device"
    SECURITY = "security"


@dataclass
class AgentStats:
    total: int = 0
    success: int = 0
    total_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 1.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.total if self.total else 0.0


@dataclass
class AgentResponse:
    agent_type: AgentType
    content: str
    success: bool
    latency_ms: float
    escalate: bool = False
    error: Optional[str] = None


@dataclass
class Request:
    message: str
    user_id: str = "anonymous"
    context: str = ""
    history: Optional[List[Dict[str, str]]] = None
    intent: Optional[IntentCategory] = None
    urgency: Optional[UrgencyLevel] = None
    entities: Dict[str, List[str]] = field(default_factory=dict)
    intent_confidence: float = 0.0
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class RoutingDecision:
    primary: AgentType
    secondary: List[AgentType]
    scores: Dict[str, float]
    reason: str

    @property
    def agents(self) -> List[AgentType]:
        return [self.primary, *self.secondary]


@dataclass
class OrchestratorResult:
    request_id: str
    response: str
    agent_type: AgentType
    intent: IntentCategory
    confidence: float
    urgency: UrgencyLevel
    entities: Dict[str, List[str]]
    clarification_required: bool
    routing_reason: str
    agent_trace: List[Dict[str, Any]]
    escalated: bool
    latency_ms: float


class BaseAgent:
    agent_type: AgentType
    system_prompt: str

    def __init__(
        self,
        client: Any,
        model: str,
        skill_manager: Optional[Any] = None,
        message_options: Optional[Dict[str, Any]] = None,
    ):
        self._client = client
        self._model = model
        self._skill_manager = skill_manager
        self._message_options = dict(message_options or {})
        self.stats = AgentStats()

    async def handle(self, request: Request) -> AgentResponse:
        started = time.monotonic()
        self.stats.total += 1
        try:
            content = await self._call_llm(request)
            latency_ms = (time.monotonic() - started) * 1000
            self.stats.success += 1
            self.stats.total_ms += latency_ms
            return AgentResponse(
                agent_type=self.agent_type,
                content=content,
                success=True,
                latency_ms=latency_ms,
                escalate=self._needs_escalation(content),
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - started) * 1000
            self.stats.total_ms += latency_ms
            logger.exception("Agent %s failed", self.agent_type.value)
            return AgentResponse(
                agent_type=self.agent_type,
                content="",
                success=False,
                latency_ms=latency_ms,
                error=type(exc).__name__,
            )

    async def _call_llm(self, request: Request) -> str:
        messages: List[Dict[str, str]] = []
        if request.context:
            messages.extend([
                {"role": "user", "content": f"[Context]\n{self._clean(request.context)}"},
                {"role": "assistant", "content": "Context received."},
            ])
        messages.append({"role": "user", "content": self._clean(request.message)})

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1200,
            temperature=0.1,
            system=self._build_system_prompt(request),
            messages=messages,
            **self._message_options,
        )
        return require_text_content(response.content, f"{self.agent_type.value} agent")

    def _build_system_prompt(self, request: Request) -> str:
        common = (
            "You are an OpsPilot enterprise IT diagnosis agent. Diagnose before recommending action. "
            "Use supplied knowledge when relevant, state uncertainty, give verification steps, and never "
            "claim that you executed a privileged operation. Do not request passwords, tokens or private keys. "
            "Reply in the user's language. Keep the answer concise: assessment, evidence, 3-6 safe steps, "
            "verification and escalation condition."
        )
        skill_prompt = ""
        if self._skill_manager is not None:
            skill_prompt = self._skill_manager.prompt_for(request.message, self.agent_type.value)
        return "\n\n".join(part for part in [common, self.system_prompt, skill_prompt] if part)

    @staticmethod
    def _needs_escalation(content: str) -> bool:
        lowered = content.lower()
        return any(word in lowered for word in ["升级处理", "转交人工", "二线", "escalate"])

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").encode("utf-8", errors="ignore").decode("utf-8")


class TriageAgent(BaseAgent):
    agent_type = AgentType.TRIAGE
    system_prompt = "Clarify the scope, affected users, occurrence time and exact symptoms before routing."


class NetworkAgent(BaseAgent):
    agent_type = AgentType.NETWORK
    system_prompt = "Focus on DNS, DHCP, VPN, proxy, routing, latency, packet loss and connectivity diagnosis."


class IdentityAccessAgent(BaseAgent):
    agent_type = AgentType.IDENTITY_ACCESS
    system_prompt = "Focus on accounts, SSO, MFA, authentication, authorization and least-privilege access."


class SoftwareAgent(BaseAgent):
    agent_type = AgentType.SOFTWARE
    system_prompt = "Focus on operating systems, applications, installation, upgrades, dependencies and logs."


class DeviceAgent(BaseAgent):
    agent_type = AgentType.DEVICE
    system_prompt = "Focus on endpoints, printers, displays, storage and peripherals using safe hardware checks."


class SecurityAgent(BaseAgent):
    agent_type = AgentType.SECURITY
    system_prompt = "Focus on containment and evidence preservation for phishing, malware, leakage and intrusion."


_INTENT_TO_AGENT = {
    IntentCategory.NETWORK: AgentType.NETWORK,
    IntentCategory.IDENTITY_ACCESS: AgentType.IDENTITY_ACCESS,
    IntentCategory.SOFTWARE: AgentType.SOFTWARE,
    IntentCategory.DEVICE: AgentType.DEVICE,
    IntentCategory.SECURITY: AgentType.SECURITY,
    IntentCategory.OTHER: AgentType.TRIAGE,
}


_ROUTING_KEYWORDS: Dict[AgentType, List[str]] = {
    AgentType.NETWORK: ["网络", "wifi", "vpn", "dns", "代理", "网关", "丢包", "断网", "延迟", "ip"],
    AgentType.IDENTITY_ACCESS: ["账号", "账户", "登录", "权限", "认证", "授权", "密码", "sso", "ldap", "401", "403"],
    AgentType.SOFTWARE: ["软件", "应用", "客户端", "程序", "安装", "升级", "崩溃", "闪退", "报错", "500"],
    AgentType.DEVICE: ["电脑", "笔记本", "打印机", "显示器", "键盘", "鼠标", "硬盘", "蓝屏", "设备", "外设"],
    AgentType.SECURITY: ["病毒", "木马", "勒索", "钓鱼", "泄露", "攻击", "异常登录", "入侵"],
    AgentType.TRIAGE: [],
}


class AgentOrchestrator:
    """Route one incident to a primary agent and, when needed, one secondary agent."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        skill_manager: Optional[Any] = None,
        recognizer: Optional[IntentRecognizer] = None,
        client: Optional[Any] = None,
    ):
        if client is None:
            kwargs: Dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = AsyncAnthropic(**kwargs)

        self._recognizer = recognizer or IntentRecognizer(
            api_key=api_key,
            base_url=base_url,
            model=model,
            client=client,
        )
        self._skill_manager = skill_manager
        message_options = llm_request_options(base_url)
        self._pool: Dict[AgentType, List[BaseAgent]] = {
            AgentType.TRIAGE: [TriageAgent(client, model, skill_manager, message_options)],
            AgentType.NETWORK: [NetworkAgent(client, model, skill_manager, message_options)],
            AgentType.IDENTITY_ACCESS: [IdentityAccessAgent(client, model, skill_manager, message_options)],
            AgentType.SOFTWARE: [SoftwareAgent(client, model, skill_manager, message_options)],
            AgentType.DEVICE: [DeviceAgent(client, model, skill_manager, message_options)],
            AgentType.SECURITY: [SecurityAgent(client, model, skill_manager, message_options)],
        }

    def set_skill_manager(self, skill_manager: Optional[Any]) -> None:
        self._skill_manager = skill_manager
        for agents in self._pool.values():
            for agent in agents:
                agent._skill_manager = skill_manager

    async def classify(self, request: Request) -> IntentResult:
        """Classify once so the API can skip RAG when clarification is required."""
        return await self._recognizer.recognize(request.message, request.history)

    async def run(
        self,
        request: Request,
        intent_result: Optional[IntentResult] = None,
    ) -> OrchestratorResult:
        started = time.monotonic()
        intent_result = intent_result or await self._resolve_intent(request)
        request.intent = intent_result.intent
        request.urgency = intent_result.urgency
        request.entities = intent_result.entities
        request.intent_confidence = intent_result.confidence
        intent_trace = {
            "stage": "intent_recognition",
            "intent": intent_result.intent.value,
            "confidence": intent_result.confidence,
            "urgency": intent_result.urgency.value,
            "status": "clarify" if intent_result.needs_clarification else "completed",
        }

        if intent_result.needs_clarification:
            return OrchestratorResult(
                request_id=request.request_id,
                response=intent_result.clarification_question or "请补充故障现象和影响范围。",
                agent_type=AgentType.TRIAGE,
                intent=intent_result.intent,
                confidence=intent_result.confidence,
                urgency=intent_result.urgency,
                entities=intent_result.entities,
                clarification_required=True,
                routing_reason="融合置信度低于阈值，暂停专业 Agent 路由并请求补充信息。",
                agent_trace=[intent_trace],
                escalated=False,
                latency_ms=(time.monotonic() - started) * 1000,
            )

        decision = self.route(request)
        responses = await asyncio.gather(
            *(self._execute(request, agent_type) for agent_type in decision.agents)
        )
        trace = [intent_trace, {
            "stage": "routing",
            "primary": decision.primary.value,
            "secondary": [agent.value for agent in decision.secondary],
            "scores": decision.scores,
            "status": "completed",
        }]
        for index, response in enumerate(responses):
            trace.append({
                "stage": "agent_execution",
                "agent": response.agent_type.value,
                "role": "primary" if index == 0 else "secondary",
                "status": "success" if response.success else "failed",
                "latency_ms": round(response.latency_ms, 1),
                "error": response.error,
            })

        successful = [response for response in responses if response.success and response.content]
        if not successful:
            fallback = await self._execute(request, AgentType.TRIAGE)
            successful = [fallback] if fallback.success else []
            trace.append({
                "stage": "fallback",
                "agent": AgentType.TRIAGE.value,
                "status": "success" if fallback.success else "failed",
                "latency_ms": round(fallback.latency_ms, 1),
                "error": fallback.error,
            })

        response_text = self._merge_responses(successful)
        escalated = (
            intent_result.urgency == UrgencyLevel.CRITICAL
            or intent_result.intent == IntentCategory.SECURITY
            or any(response.escalate for response in successful)
        )
        return OrchestratorResult(
            request_id=request.request_id,
            response=response_text,
            agent_type=decision.primary,
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            urgency=intent_result.urgency,
            entities=intent_result.entities,
            clarification_required=False,
            routing_reason=decision.reason,
            agent_trace=trace,
            escalated=escalated,
            latency_ms=(time.monotonic() - started) * 1000,
        )

    def route(self, request: Request) -> RoutingDecision:
        scores = {agent_type: 0.0 for agent_type in AgentType}
        reasons: Dict[AgentType, List[str]] = {agent_type: [] for agent_type in AgentType}

        mapped = _INTENT_TO_AGENT.get(request.intent or IntentCategory.OTHER, AgentType.TRIAGE)
        scores[mapped] += 0.60
        reasons[mapped].append(f"intent={request.intent.value if request.intent else 'other'}")

        history_text = " ".join(item.get("content", "") for item in (request.history or [])[-3:])
        searchable = f"{request.message} {history_text}".lower()
        for agent_type, keywords in _ROUTING_KEYWORDS.items():
            matched = [keyword for keyword in keywords if keyword in searchable]
            if matched:
                scores[agent_type] += min(0.35, 0.12 + len(matched) * 0.06)
                reasons[agent_type].append(f"keywords={','.join(matched[:4])}")

        entity_agents = {
            "ip_address": AgentType.NETWORK,
            "hostname": AgentType.NETWORK,
            "network_service": AgentType.NETWORK,
            "account": AgentType.IDENTITY_ACCESS,
            "software": AgentType.SOFTWARE,
            "device": AgentType.DEVICE,
        }
        for entity_type, values in request.entities.items():
            agent_type = entity_agents.get(entity_type)
            if agent_type and values:
                scores[agent_type] += 0.15
                reasons[agent_type].append(f"entity={entity_type}")

        scores = {agent: min(score, 1.0) for agent, score in scores.items()}
        ranked = sorted(scores, key=scores.get, reverse=True)
        primary = ranked[0]
        secondary = [
            agent for agent in ranked[1:]
            if agent != AgentType.TRIAGE and scores[agent] >= 0.18
        ][:1]

        primary_detail = "; ".join(reasons[primary]) or "default triage"
        reason = f"主 Agent={primary.value}({scores[primary]:.2f})，依据：{primary_detail}"
        if secondary:
            second = secondary[0]
            second_detail = "; ".join(reasons[second])
            reason += f"；辅 Agent={second.value}({scores[second]:.2f})，依据：{second_detail}"

        return RoutingDecision(
            primary=primary,
            secondary=secondary,
            scores={agent.value: round(score, 3) for agent, score in scores.items()},
            reason=reason,
        )

    async def _resolve_intent(self, request: Request) -> IntentResult:
        if request.intent is None:
            result = await self._recognizer.recognize(request.message, request.history)
            request.intent = result.intent
            request.urgency = result.urgency
            request.entities = result.entities
            request.intent_confidence = result.confidence
            return result

        return IntentResult(
            intent=request.intent,
            confidence=request.intent_confidence or 1.0,
            urgency=request.urgency or UrgencyLevel.LOW,
            entities=request.entities,
            reasoning="intent supplied by caller",
            needs_clarification=False,
            clarification_question=None,
        )

    def _best_agent(self, agent_type: AgentType) -> Optional[BaseAgent]:
        agents = self._pool.get(agent_type, [])
        if not agents:
            return None
        return max(agents, key=lambda agent: (agent.stats.success_rate, -agent.stats.avg_ms))

    async def _execute(self, request: Request, agent_type: AgentType) -> AgentResponse:
        agent = self._best_agent(agent_type)
        if agent is None:
            return AgentResponse(agent_type, "", False, 0.0, error="agent unavailable")
        return await agent.handle(request)

    @staticmethod
    def _merge_responses(responses: List[AgentResponse]) -> str:
        if not responses:
            return "当前诊断服务不可用，请记录故障时间、影响范围和错误信息后转交人工处理。"
        if len(responses) == 1:
            return responses[0].content
        sections = []
        for index, response in enumerate(responses):
            role = "主诊断" if index == 0 else "辅助诊断"
            sections.append(f"[{role} · {response.agent_type.value}]\n{response.content}")
        return "\n\n".join(sections)

    def get_stats(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for agent_type, agents in self._pool.items():
            total = sum(agent.stats.total for agent in agents)
            success = sum(agent.stats.success for agent in agents)
            total_ms = sum(agent.stats.total_ms for agent in agents)
            result[agent_type.value] = {
                "total": total,
                "success_rate": round(success / total, 3) if total else None,
                "avg_ms": round(total_ms / total, 1) if total else 0.0,
            }
        return result
