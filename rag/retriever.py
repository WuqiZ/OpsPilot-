"""Query rewrite, parallel recall, deduplication and LLM reranking."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from core.llm_utils import llm_request_options, require_text_content
from rag.knowledge_base import KnowledgeBase


@dataclass
class RetrievalResult:
    items: List[Dict[str, Any]]
    rewritten_queries: List[str]
    reranked: bool


class RAGRetriever:
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        client: Optional[Any] = None,
    ):
        if client is None:
            kwargs: Dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = AsyncAnthropic(**kwargs)
        self._client = client
        self._model = model
        self._knowledge_base = knowledge_base
        self._message_options = llm_request_options(base_url)

    async def retrieve(self, query: str, top_k: int = 4) -> RetrievalResult:
        queries = await self.rewrite_query(query)
        batches = await asyncio.gather(*(
            self._knowledge_base.search(sub_query, top_k=max(top_k, 4), source="all")
            for sub_query in queries
        ))
        candidates = self._deduplicate([item for batch in batches for item in batch])
        reranked_items, reranked = await self._rerank(query, candidates, top_k)
        return RetrievalResult(reranked_items, queries, reranked)

    async def rewrite_query(self, query: str, count: int = 3) -> List[str]:
        prompt = (
            f"Rewrite this enterprise IT incident into {count} short retrieval queries from different angles: "
            "symptom, likely dependency and verification. Return a JSON string array only.\n"
            f"Incident: {self._clean(query)}"
        )
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=250,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
                **self._message_options,
            )
            raw = require_text_content(response.content, "query rewrite")
            start, end = raw.find("["), raw.rfind("]") + 1
            rewritten = json.loads(raw[start:end])
            values = [query, *(str(item).strip() for item in rewritten if str(item).strip())]
            return list(dict.fromkeys(values))[: count + 1]
        except Exception:
            return [query]

    async def _rerank(
        self,
        query: str,
        items: List[Dict[str, Any]],
        top_k: int,
    ) -> tuple[List[Dict[str, Any]], bool]:
        if len(items) <= top_k:
            return items, False

        candidates = "\n".join(
            f"{index}. [{item['source']}] {item['title']}: {item['content'][:300]}"
            for index, item in enumerate(items)
        )
        prompt = (
            "Rank the candidate evidence by usefulness for diagnosing the incident. "
            "Return a JSON array containing each candidate index once, best first.\n"
            f"Incident: {self._clean(query)}\nCandidates:\n{self._clean(candidates)}"
        )
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=250,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
                **self._message_options,
            )
            raw = require_text_content(response.content, "RAG rerank")
            start, end = raw.find("["), raw.rfind("]") + 1
            order = json.loads(raw[start:end])
            valid = list(dict.fromkeys(index for index in order if isinstance(index, int) and 0 <= index < len(items)))
            valid.extend(index for index in range(len(items)) if index not in valid)
            return [items[index] for index in valid[:top_k]], True
        except Exception:
            return sorted(items, key=lambda item: item.get("score", 0.0), reverse=True)[:top_k], False

    @staticmethod
    def _deduplicate(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        unique: Dict[str, Dict[str, Any]] = {}
        for item in items:
            key = hashlib.sha256(str(item.get("content", "")).encode("utf-8")).hexdigest()
            if key not in unique or item.get("score", 0.0) > unique[key].get("score", 0.0):
                unique[key] = item
        return list(unique.values())

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").encode("utf-8", errors="ignore").decode("utf-8")
