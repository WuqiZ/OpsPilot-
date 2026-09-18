"""Typed evaluation cases and loading for reproducible offline benchmarks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class IntentTestCase:
    message: str
    expected_intent: str
    expect_clarification: bool = False


@dataclass(frozen=True)
class RoutingTestCase:
    message: str
    intent: str
    expected_primary: str
    expected_secondary: List[str] = field(default_factory=list)
    entities: Dict[str, List[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalTestCase:
    query: str
    expected_titles: List[str]
    top_k: int = 4


@dataclass(frozen=True)
class DialogTestCase:
    question: str
    expected_primary: Optional[str] = None
    min_overall: float = 0.75


@dataclass(frozen=True)
class EvaluationDataset:
    name: str
    version: str
    provenance: str
    intent_cases: List[IntentTestCase]
    routing_cases: List[RoutingTestCase]
    retrieval_cases: List[RetrievalTestCase]
    dialog_cases: List[DialogTestCase]

    @property
    def total(self) -> int:
        return sum((
            len(self.intent_cases),
            len(self.routing_cases),
            len(self.retrieval_cases),
            len(self.dialog_cases),
        ))

    @property
    def breakdown(self) -> Dict[str, int]:
        return {
            "intent": len(self.intent_cases),
            "routing": len(self.routing_cases),
            "retrieval": len(self.retrieval_cases),
            "dialog": len(self.dialog_cases),
        }


def load_evaluation_dataset(path: str | Path) -> EvaluationDataset:
    """Load and validate a committed JSON evaluation dataset."""
    source = Path(path).expanduser().resolve()
    data: Dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    metadata = dict(data.get("metadata") or {})
    dataset = EvaluationDataset(
        name=str(metadata.get("name") or source.stem),
        version=str(metadata.get("version") or "1.0"),
        provenance=str(metadata.get("provenance") or "unspecified"),
        intent_cases=[IntentTestCase(**item) for item in data.get("intent_cases", [])],
        routing_cases=[RoutingTestCase(**item) for item in data.get("routing_cases", [])],
        retrieval_cases=[RetrievalTestCase(**item) for item in data.get("retrieval_cases", [])],
        dialog_cases=[DialogTestCase(**item) for item in data.get("dialog_cases", [])],
    )
    expected_total = int(metadata.get("expected_total", dataset.total))
    if dataset.total != expected_total:
        raise ValueError(f"dataset contains {dataset.total} cases; expected {expected_total}")
    if not all(dataset.breakdown.values()):
        raise ValueError("dataset must contain intent, routing, retrieval and dialog cases")

    _ensure_unique("intent", [case.message for case in dataset.intent_cases])
    _ensure_unique("routing", [case.message for case in dataset.routing_cases])
    _ensure_unique("retrieval", [case.query for case in dataset.retrieval_cases])
    _ensure_unique("dialog", [case.question for case in dataset.dialog_cases])
    return dataset


def _ensure_unique(section: str, values: List[str]) -> None:
    normalized = [value.strip().casefold() for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{section} section contains duplicate cases")
