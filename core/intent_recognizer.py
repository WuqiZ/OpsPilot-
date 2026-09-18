"""Fine-grained intent recognition for enterprise IT incidents."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from anthropic import AsyncAnthropic
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from core.llm_utils import llm_request_options, parse_json_object, require_text_content


logger = logging.getLogger(__name__)


class IntentCategory(str, Enum):
    NETWORK = "network"
    IDENTITY_ACCESS = "identity_access"
    SOFTWARE = "software"
    DEVICE = "device"
    SECURITY = "security"
    OTHER = "other"


class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class IntentResult:
    intent: IntentCategory
    confidence: float
    urgency: UrgencyLevel
    entities: Dict[str, List[str]]
    reasoning: str
    needs_clarification: bool
    clarification_question: Optional[str]
    scores: Dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0


_TEMPLATES: Dict[IntentCategory, List[str]] = {
    IntentCategory.NETWORK: [
        "公司 WiFi 连不上，VPN 一直超时",
        "内网 DNS 无法解析服务器域名",
        "办公室网络丢包很严重",
    ],
    IntentCategory.IDENTITY_ACCESS: [
        "企业账号被锁定，无法登录",
        "我没有共享目录的访问权限",
        "单点登录提示 403 forbidden",
    ],
    IntentCategory.SOFTWARE: [
        "办公软件启动后立即崩溃",
        "客户端升级后一直报 500 错误",
        "应用安装失败并提示依赖缺失",
    ],
    IntentCategory.DEVICE: [
        "笔记本无法开机",
        "打印机离线不能打印",
        "显示器闪屏并且扩展坞无法识别",
    ],
    IntentCategory.SECURITY: [
        "电脑疑似中了勒索病毒",
        "账号出现异常登录记录",
        "我可能误点了钓鱼邮件",
    ],
}


_DOMAIN_KEYWORDS: Dict[IntentCategory, List[str]] = {
    IntentCategory.NETWORK: [
        "网络", "wifi", "vpn", "dns", "丢包", "断网", "延迟", "代理", "网关", "ip", "无法连接",
    ],
    IntentCategory.IDENTITY_ACCESS: [
        "账号", "账户", "登录", "权限", "认证", "授权", "密码", "单点登录", "sso", "ldap", "401", "403",
    ],
    IntentCategory.SOFTWARE: [
        "软件", "应用", "客户端", "程序", "安装", "升级", "崩溃", "闪退", "报错", "500", "依赖",
    ],
    IntentCategory.DEVICE: [
        "电脑", "笔记本", "打印机", "显示器", "键盘", "鼠标", "硬盘", "蓝屏", "无法开机", "设备", "外设",
    ],
    IntentCategory.SECURITY: [
        "病毒", "木马", "勒索", "钓鱼", "泄露", "攻击", "异常登录", "恶意", "入侵", "安全事件",
    ],
}


_ENTITY_KEYWORDS: Dict[str, List[str]] = {
    "network_service": ["vpn", "dns", "wifi", "dhcp", "代理", "网关"],
    "software": ["office", "outlook", "teams", "chrome", "edge", "客户端", "浏览器"],
    "device": ["笔记本", "电脑", "打印机", "显示器", "键盘", "鼠标", "硬盘", "扩展坞"],
    "environment": ["生产环境", "测试环境", "开发环境", "公司内网", "办公网"],
}


class IntentRecognizer:
    """Fuse LLM Few-shot, local embeddings and keyword patterns."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        confidence_threshold: float = 0.55,
        client: Optional[Any] = None,
        embedding_function: Optional[Any] = None,
        use_model_embeddings: bool = True,
    ):
        if client is None:
            kwargs: Dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = AsyncAnthropic(**kwargs)
        self.client = client
        self.model = model
        self.threshold = confidence_threshold
        self._message_options = llm_request_options(base_url)
        if embedding_function is not None:
            self._embedding_function = embedding_function
        elif use_model_embeddings:
            self._embedding_function = DefaultEmbeddingFunction()
        else:
            self._embedding_function = None
        self._template_vectors: Dict[IntentCategory, List[List[float]]] = {}
        self._cache: Dict[str, IntentResult] = {}

    async def recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> IntentResult:
        message = self._clean_text(message).strip()
        cache_key = self._cache_key(message, history)
        if cache_key in self._cache:
            return self._cache[cache_key]

        started = time.monotonic()
        llm_task = asyncio.create_task(self._llm_recognize(message, history))
        embedding_task = asyncio.create_task(self._embedding_recognize(message))
        pattern = self._pattern_recognize(message)
        llm, embedding = await asyncio.gather(llm_task, embedding_task)

        intent, confidence, scores = self._vote(llm, embedding, pattern)
        entities = self._merge_entities(
            self._extract_local_entities(message),
            llm.get("entities", {}),
        )
        urgency = self._resolve_urgency(message, intent, llm.get("urgency"))
        needs_clarification = intent == IntentCategory.OTHER or (
            confidence < self.threshold and intent != IntentCategory.SECURITY
        )
        clarification = self._clarification_question(intent, scores) if needs_clarification else None

        result = IntentResult(
            intent=intent,
            confidence=round(confidence, 4),
            urgency=urgency,
            entities=entities,
            reasoning=str(llm.get("reasoning") or self._local_reason(intent, pattern)),
            needs_clarification=needs_clarification,
            clarification_question=clarification,
            scores={key.value: round(value, 4) for key, value in scores.items()},
            latency_ms=(time.monotonic() - started) * 1000,
        )
        self._remember(cache_key, result)
        return result

    async def _llm_recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        examples = "\n".join(
            f'- "{samples[0]}" -> {category.value}'
            for category, samples in _TEMPLATES.items()
        )
        context = ""
        if history:
            context = "\nRecent context:\n" + "\n".join(
                f"{self._clean_text(item.get('role', 'user'))}: "
                f"{self._clean_text(item.get('content', ''))}"
                for item in history[-4:]
            )

        prompt = f"""Classify this enterprise IT support request.

Categories:
- network: connectivity, VPN, DNS, proxy, latency or packet loss
- identity_access: account, login, authentication, authorization or permissions
- software: application, operating system, installation, upgrade or runtime failure
- device: computer hardware, printer, display or peripherals
- security: malware, phishing, data leakage, intrusion or suspicious access
- other: insufficient or unrelated information

Examples:
{examples}
{context}
Request: {message}

Return JSON only:
{{"intent":"network|identity_access|software|device|security|other",
"confidence":0.0,"urgency":"low|medium|high|critical",
        "reasoning":"brief reason","entities":{{"ip_address":[],"hostname":[],
        "error_code":[],"account":[],"network_service":[],"software":[],"device":[],
        "environment":[]}}}}"""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=400,
                temperature=0.0,
                messages=[{"role": "user", "content": self._clean_text(prompt)}],
                **self._message_options,
            )
            data = parse_json_object(require_text_content(response.content, "intent classification"))
            try:
                intent = IntentCategory(str(data.get("intent", "other")))
            except ValueError:
                intent = IntentCategory.OTHER
            return {
                "intent": intent,
                "confidence": self._clamp(data.get("confidence", 0.0)),
                "urgency": data.get("urgency"),
                "reasoning": data.get("reasoning", ""),
                "entities": data.get("entities", {}),
            }
        except Exception as exc:
            logger.warning("LLM intent classification failed: %s", type(exc).__name__)
            return {
                "intent": IntentCategory.OTHER,
                "confidence": 0.0,
                "reasoning": "LLM classification unavailable; used local strategies",
                "entities": {},
                "failed": True,
            }

    async def _embedding_recognize(self, message: str) -> Dict[str, Any]:
        for category, samples in _TEMPLATES.items():
            if category not in self._template_vectors:
                self._template_vectors[category] = await asyncio.gather(*(
                    self._embed_text(text) for text in samples
                ))

        message_vector = await self._embed_text(message)
        scores = {
            category: max(self._cosine(message_vector, vector) for vector in vectors)
            for category, vectors in self._template_vectors.items()
        }
        best = max(scores, key=scores.get)
        return {"intent": best, "confidence": max(0.0, scores[best])}

    async def _embed_text(self, text: str) -> List[float]:
        if self._embedding_function is not None:
            try:
                vectors = await asyncio.to_thread(self._embedding_function, [text])
                return [float(value) for value in vectors[0]]
            except Exception as exc:
                logger.warning("Model embedding failed, using local fallback: %s", type(exc).__name__)
        return self._local_embedding(text)

    def _pattern_recognize(self, message: str) -> Dict[str, Any]:
        lowered = message.lower()
        hits = {
            category: [keyword for keyword in keywords if keyword in lowered]
            for category, keywords in _DOMAIN_KEYWORDS.items()
        }
        best = max(hits, key=lambda category: len(hits[category]))
        count = len(hits[best])
        if count == 0:
            return {"intent": IntentCategory.OTHER, "confidence": 0.0, "hits": []}
        confidence = min(0.95, 0.55 + 0.12 * (count - 1))
        return {"intent": best, "confidence": confidence, "hits": hits[best]}

    def _vote(
        self,
        llm: Dict[str, Any],
        embedding: Dict[str, Any],
        pattern: Dict[str, Any],
    ) -> tuple[IntentCategory, float, Dict[IntentCategory, float]]:
        sources = (
            [(embedding, 0.65), (pattern, 0.35)]
            if llm.get("failed")
            else [(llm, 0.65), (embedding, 0.25), (pattern, 0.10)]
        )
        scores = {category: 0.0 for category in IntentCategory}
        for source, weight in sources:
            category = source.get("intent", IntentCategory.OTHER)
            if not isinstance(category, IntentCategory):
                category = IntentCategory.OTHER
            scores[category] += weight * self._clamp(source.get("confidence", 0.0))

        best = max(scores, key=scores.get)
        return best, scores[best], scores

    def _extract_local_entities(self, message: str) -> Dict[str, List[str]]:
        lowered = message.lower()
        entities: Dict[str, List[str]] = {
            "ip_address": re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", message),
            "hostname": re.findall(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b", message),
            "error_code": re.findall(r"\b(?:[45]\d{2}|0x[0-9a-fA-F]+|ERR_[A-Z0-9_]+)\b", message),
            "account": re.findall(r"(?:账号|账户|用户)[：:\s]*([A-Za-z0-9_.@-]{3,})", message),
        }
        for entity_type, keywords in _ENTITY_KEYWORDS.items():
            entities[entity_type] = [keyword for keyword in keywords if keyword in lowered]
        return {key: list(dict.fromkeys(values)) for key, values in entities.items() if values}

    @staticmethod
    def _merge_entities(*sources: Any) -> Dict[str, List[str]]:
        merged: Dict[str, List[str]] = {}
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key, raw_values in source.items():
                values: Sequence[Any] = raw_values if isinstance(raw_values, list) else [raw_values]
                cleaned = [str(value).strip() for value in values if str(value).strip()]
                if cleaned:
                    merged.setdefault(str(key), []).extend(cleaned)
        network_terms = {"vpn", "dns", "wifi", "dhcp", "proxy", "gateway", "代理", "网关"}
        software = merged.get("software", [])
        network_values = [value for value in software if value.lower() in network_terms]
        if network_values:
            merged.setdefault("network_service", []).extend(network_values)
            merged["software"] = [value for value in software if value.lower() not in network_terms]
        normalized: Dict[str, List[str]] = {}
        for key, values in merged.items():
            seen = set()
            unique = []
            for value in values:
                marker = value.casefold()
                if marker not in seen:
                    seen.add(marker)
                    unique.append(value)
            if unique:
                normalized[key] = unique
        return normalized

    @staticmethod
    def _resolve_urgency(
        message: str,
        intent: IntentCategory,
        llm_urgency: Any,
    ) -> UrgencyLevel:
        lowered = message.lower()
        if any(word in lowered for word in ["勒索", "数据泄露", "全公司", "大面积", "核心业务中断"]):
            return UrgencyLevel.CRITICAL
        if any(word in lowered for word in ["生产故障", "无法办公", "多人", "紧急", "立即"]):
            return UrgencyLevel.HIGH
        if re.search(
            r"(?:[2-9]|\d{2,}|[二两三四五六七八九十百]+)\s*(?:人|位|个(?:用户|员工)?)"
            r"[^。；，,]{0,12}(?:受影响|无法|失败|异常)",
            lowered,
        ):
            return UrgencyLevel.HIGH
        if intent == IntentCategory.SECURITY:
            return UrgencyLevel.HIGH
        try:
            return UrgencyLevel(str(llm_urgency))
        except ValueError:
            return UrgencyLevel.MEDIUM if "持续" in lowered else UrgencyLevel.LOW

    @staticmethod
    def _clarification_question(
        intent: IntentCategory,
        scores: Dict[IntentCategory, float],
    ) -> str:
        ranked = sorted(scores, key=scores.get, reverse=True)
        candidates = [category.value for category in ranked[:2] if category != IntentCategory.OTHER]
        hint = f"目前更接近 {' 或 '.join(candidates)}。" if candidates else ""
        questions = {
            IntentCategory.NETWORK: "请补充是 WiFi、VPN、DNS 还是某个地址无法访问，并说明影响范围。",
            IntentCategory.IDENTITY_ACCESS: "请补充登录入口、错误码，以及是单个账号还是多人受影响。",
            IntentCategory.SOFTWARE: "请补充软件名称、版本、操作系统和完整报错信息。",
            IntentCategory.DEVICE: "请补充设备类型、型号、故障现象，以及电源或指示灯状态。",
            IntentCategory.SECURITY: "请说明发现了什么异常、影响哪些设备；不要发送密码或密钥。",
            IntentCategory.OTHER: "请说明问题主要涉及网络、账号权限、软件还是设备，并补充错误信息和影响范围。",
        }
        return hint + questions[intent]

    @staticmethod
    def _local_reason(intent: IntentCategory, pattern: Dict[str, Any]) -> str:
        hits = pattern.get("hits") or []
        return f"matched {intent.value} signals: {', '.join(hits)}" if hits else "insufficient signals"

    @staticmethod
    def _local_embedding(text: str, dimensions: int = 256) -> List[float]:
        normalized = text.lower().strip()
        vector = [0.0] * dimensions
        tokens = {
            normalized[index:index + size]
            for size in (1, 2, 3)
            for index in range(max(0, len(normalized) - size + 1))
        }
        for token in tokens or {normalized}:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        return vector

    @staticmethod
    def _cosine(left: List[float], right: List[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            return min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").encode("utf-8", errors="ignore").decode("utf-8")

    def _cache_key(self, message: str, history: Optional[List[Dict[str, str]]]) -> str:
        context = "|".join(str(item.get("content", "")) for item in (history or [])[-3:])
        return hashlib.sha256(f"{message}|{context}".encode("utf-8")).hexdigest()

    def _remember(self, key: str, result: IntentResult) -> None:
        if len(self._cache) >= 1000:
            for old_key in list(self._cache)[:250]:
                del self._cache[old_key]
        self._cache[key] = result
