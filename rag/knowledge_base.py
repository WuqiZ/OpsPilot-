"""ChromaDB storage for operations knowledge and historical incidents."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, Iterable, List, Optional

import chromadb


logger = logging.getLogger(__name__)

KNOWLEDGE = "knowledge"
INCIDENT = "incident"
VALID_SOURCES = {KNOWLEDGE, INCIDENT}


class KnowledgeBase:
    """Maintain separate collections for SOP knowledge and incident cases."""

    def __init__(
        self,
        chroma_host: str = "localhost",
        chroma_port: int = 8000,
        chroma_path: str = "./data/chroma",
        mode: str = "local",
    ):
        settings = chromadb.Settings(anonymized_telemetry=False)
        if mode == "server":
            client = chromadb.HttpClient(host=chroma_host, port=chroma_port, settings=settings)
            client.heartbeat()
            logger.info("Connected to ChromaDB at %s:%s", chroma_host, chroma_port)
        elif mode == "local":
            client = chromadb.PersistentClient(path=chroma_path, settings=settings)
            logger.info("Using embedded ChromaDB at %s", chroma_path)
        else:
            raise ValueError("mode must be 'local' or 'server'")

        self._collections = {
            KNOWLEDGE: client.get_or_create_collection(
                "opspilot_operations_knowledge",
                metadata={"description": "Enterprise IT operations knowledge and SOPs"},
            ),
            INCIDENT: client.get_or_create_collection(
                "opspilot_incident_cases",
                metadata={"description": "Resolved enterprise IT incident cases"},
            ),
        }
        self._seed_defaults()

    def add_documents(self, documents: List[Dict[str, str]], source: str = KNOWLEDGE) -> int:
        if source not in VALID_SOURCES:
            raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}")

        ids: List[str] = []
        texts: List[str] = []
        metadata: List[Dict[str, Any]] = []
        for document in documents:
            title = str(document.get("title", "")).strip()
            content = str(document.get("content", "")).strip()
            for index, chunk in enumerate(self._chunk(content)):
                digest = hashlib.sha256(f"{source}|{title}|{index}|{chunk}".encode("utf-8")).hexdigest()
                ids.append(digest)
                texts.append(chunk)
                metadata.append({"title": title, "source": source, "chunk": index})

        if ids:
            self._collections[source].upsert(ids=ids, documents=texts, metadatas=metadata)
        return len(ids)

    async def search(self, query: str, top_k: int = 5, source: str = "all") -> List[Dict[str, Any]]:
        sources = list(VALID_SOURCES) if source == "all" else [source]
        if any(item not in VALID_SOURCES for item in sources):
            raise ValueError(f"source must be all or one of {sorted(VALID_SOURCES)}")

        batches = await asyncio.gather(*(
            asyncio.to_thread(self._query_collection, item, query, top_k)
            for item in sources
        ))
        items = [item for batch in batches for item in batch]
        items.sort(key=lambda item: item["score"], reverse=True)
        return items[: top_k * len(sources)]

    def stats(self) -> Dict[str, int]:
        return {source: collection.count() for source, collection in self._collections.items()}

    def list_documents(self, source: str = "all", limit: int = 100) -> List[Dict[str, Any]]:
        """Read stored chunks without embedding or calling the LLM."""
        sources = [KNOWLEDGE, INCIDENT] if source == "all" else [source]
        if any(value not in VALID_SOURCES for value in sources):
            raise ValueError("invalid knowledge source")
        items: List[Dict[str, Any]] = []
        for name in sources:
            remaining = limit - len(items)
            if remaining <= 0:
                break
            records = self._collections[name].get(limit=remaining, include=["documents", "metadatas"])
            for key, document, metadata in zip(
                records.get("ids") or [], records.get("documents") or [], records.get("metadatas") or [],
            ):
                items.append({"id": key, "content": document, **(metadata or {}), "source": name})
        return items

    def _query_collection(self, source: str, query: str, top_k: int) -> List[Dict[str, Any]]:
        collection = self._collections[source]
        count = collection.count()
        if count == 0:
            return []
        result = collection.query(query_texts=[query], n_results=min(top_k, count))
        documents = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        distances = result.get("distances") or [[]]
        return [
            {
                "title": metadata.get("title", ""),
                "content": document,
                "source": source,
                "score": round(1.0 - float(distance), 4),
            }
            for document, metadata, distance in zip(documents[0], metadatas[0], distances[0])
        ]

    @staticmethod
    def _chunk(text: str, max_chars: int = 600) -> Iterable[str]:
        if not text:
            return []
        sentences = [sentence.strip() for sentence in text.replace("\n", "。").split("。") if sentence.strip()]
        chunks: List[str] = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 > max_chars and current:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current}。{sentence}" if current else sentence
        if current:
            chunks.append(current)
        return chunks

    def _seed_defaults(self) -> None:
        if self._collections[KNOWLEDGE].count() == 0:
            self.add_documents(_DEFAULT_KNOWLEDGE, KNOWLEDGE)
        if self._collections[INCIDENT].count() == 0:
            self.add_documents(_DEFAULT_INCIDENTS, INCIDENT)


_DEFAULT_KNOWLEDGE = [
    {
        "title": "VPN 连接故障排查 SOP",
        "content": (
            "先确认本地网络是否正常，再核对 VPN 客户端版本、账号状态和 MFA。"
            "记录错误码、发生时间和受影响人数。若多人同时失败，检查 VPN 网关和身份认证服务。"
            "不要要求用户发送密码、Token 或私钥。"
        ),
    },
    {
        "title": "账号权限故障排查 SOP",
        "content": (
            "401 优先检查凭证是否过期，403 优先检查资源授权和用户组。"
            "确认是单个账号还是批量账号受影响，并核对最近的权限变更。"
            "权限调整必须遵守最小权限原则并由授权人员审批。"
        ),
    },
    {
        "title": "终端与软件故障采集规范",
        "content": (
            "软件故障需采集软件名称、版本、操作系统、完整错误码和最近变更。"
            "设备故障需采集型号、资产编号、电源及指示灯状态。"
            "优先执行无损检查，禁止未经备份删除数据或重置生产设备。"
        ),
    },
    {
        "title": "安全事件处置原则",
        "content": (
            "发现钓鱼、恶意软件、异常登录或数据泄露时，优先隔离风险并保留证据。"
            "不要自行删除日志或格式化设备，应立即升级安全响应团队。"
        ),
    },
]


_DEFAULT_INCIDENTS = [
    {
        "title": "历史案例：VPN 全员认证失败",
        "content": (
            "现象为多名员工 VPN 提示认证失败，但普通网络正常。"
            "通过时间范围和影响面确认公共依赖，最终定位为 LDAP 证书过期。"
            "处置后验证 VPN 登录、MFA 和内部系统访问。"
        ),
    },
    {
        "title": "历史案例：升级后客户端崩溃",
        "content": (
            "客户端升级后启动即崩溃，事件日志显示缺少运行库。"
            "回滚验证成功后补装依赖并灰度发布，最后检查启动、登录和核心功能。"
        ),
    },
    {
        "title": "历史案例：打印机显示离线",
        "content": (
            "同楼层多人无法打印，设备面板正常但队列离线。"
            "排查交换机端口、打印机 IP 和打印服务，最终发现 DHCP 地址变更。"
        ),
    },
]
