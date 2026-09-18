"""LLM helpers shared by Anthropic and compatible providers."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional


def extract_text_content(content: Iterable[Any]) -> str:
    """Return text blocks from Anthropic-style response content."""
    texts: List[str] = []
    for block in content or []:
        if isinstance(block, str):
            texts.append(block)
            continue

        block_type = getattr(block, "type", None)
        text = getattr(block, "text", None)
        if isinstance(block, dict):
            block_type = block.get("type", block_type)
            text = block.get("text", text)

        if isinstance(text, str) and (block_type in (None, "text")):
            texts.append(text)

    return "\n".join(t for t in texts if t)


def require_text_content(content: Iterable[Any], operation: str = "LLM request") -> str:
    """Return final text or fail explicitly when a provider emits only thinking blocks."""
    blocks = list(content or [])
    text = extract_text_content(blocks).strip()
    if text:
        return text

    block_types = sorted({
        str(block.get("type") if isinstance(block, dict) else getattr(block, "type", "unknown"))
        for block in blocks
    })
    detail = ",".join(block_types) if block_types else "none"
    raise ValueError(f"{operation} returned no final text blocks (types={detail})")


def parse_json_object(text: str) -> Dict[str, Any]:
    """Extract the first valid JSON object from plain or Markdown-wrapped model output."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model did not return a valid JSON object")


def llm_request_options(base_url: Optional[str]) -> Dict[str, Any]:
    """Return provider-specific options without leaking them to official Anthropic."""
    normalized = str(base_url or "").rstrip("/").lower()
    if "api.deepseek.com/anthropic" not in normalized:
        return {}

    thinking_mode = os.getenv("DEEPSEEK_THINKING_MODE", "disabled").strip().lower()
    reasoning_effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "low").strip().lower()
    extra_body: Dict[str, Any] = {}
    if thinking_mode in {"enabled", "disabled"}:
        extra_body["thinking"] = {"type": thinking_mode}
    if reasoning_effort in {"low", "medium", "high", "max"}:
        extra_body["output_config"] = {"effort": reasoning_effort}
    return {"extra_body": extra_body} if extra_body else {}
