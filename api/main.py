"""FastAPI entry point for the OpsPilot IT diagnosis platform."""

from __future__ import annotations

import logging
import json
import os
import pathlib
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any, Dict, List, Literal, Optional


ROOT = pathlib.Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.agent_orchestrator import AgentOrchestrator, Request
from core.intent_recognizer import IntentRecognizer
from core.skill_loader import SkillManager
from evaluation.cases import DialogTestCase, IntentTestCase, RetrievalTestCase, RoutingTestCase
from evaluation.evaluator import EndToEndEvaluator
from rag.knowledge_base import INCIDENT, KNOWLEDGE, KnowledgeBase
from rag.retriever import RAGRetriever, RetrievalResult


load_dotenv()
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_orchestrator: Optional[AgentOrchestrator] = None
_skills: Optional[SkillManager] = None
_knowledge_base: Optional[KnowledgeBase] = None
_retriever: Optional[RAGRetriever] = None
_evaluator: Optional[EndToEndEvaluator] = None


def _llm_config() -> Dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required")
    config: Dict[str, Any] = {
        "api_key": api_key,
        "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip(),
    }
    base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
    if base_url:
        config["base_url"] = base_url
    return config


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _orchestrator, _skills, _knowledge_base, _retriever, _evaluator

    config = _llm_config()
    client_kwargs = {"api_key": config["api_key"]}
    if config.get("base_url"):
        client_kwargs["base_url"] = config["base_url"]
    client = AsyncAnthropic(**client_kwargs)

    _skills = SkillManager(
        root_dir=os.getenv("OPSPILOT_SKILLS_DIR", str(ROOT / "skills")),
        max_prompt_chars=int(os.getenv("OPSPILOT_SKILLS_MAX_PROMPT_CHARS", "5000")),
    )
    _skills.load()

    recognizer = IntentRecognizer(
        api_key=config["api_key"],
        base_url=config.get("base_url"),
        model=config["model"],
        confidence_threshold=float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.55")),
        client=client,
    )
    _orchestrator = AgentOrchestrator(
        api_key=config["api_key"],
        base_url=config.get("base_url"),
        model=config["model"],
        skill_manager=_skills,
        recognizer=recognizer,
        client=client,
    )

    _knowledge_base = KnowledgeBase(
        chroma_host=os.getenv("CHROMA_HOST", "chromadb"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", str(ROOT / "data" / "chroma")),
        mode=os.getenv("CHROMA_MODE", "local").strip().lower(),
    )
    _retriever = RAGRetriever(
        knowledge_base=_knowledge_base,
        api_key=config["api_key"],
        base_url=config.get("base_url"),
        model=config["model"],
        client=client,
    )
    _evaluator = EndToEndEvaluator(
        orchestrator=_orchestrator,
        retriever=_retriever,
        api_key=config["api_key"],
        base_url=config.get("base_url"),
        model=config["model"],
        baseline_path=os.getenv(
            "EVAL_BASELINE_PATH",
            str(ROOT / "data" / "eval" / "opspilot_baseline.json"),
        ),
        dataset_path=os.getenv(
            "EVAL_DATASET_PATH",
            str(ROOT / "evaluation" / "datasets" / "opspilot_eval_200.json"),
        ),
        client=client,
    )
    logger.info("OpsPilot is ready with model=%s", config["model"])
    yield
    logger.info("OpsPilot stopped")


app = FastAPI(
    title="OpsPilot Enterprise IT Diagnosis Agent Platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/assets", StaticFiles(directory=ROOT / "frontend"), name="frontend")


@app.get("/", include_in_schema=False)
def console() -> FileResponse:
    return FileResponse(ROOT / "frontend" / "index.html")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    user_id: str = "anonymous"
    context: Optional[str] = None
    history: List[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    request_id: str
    response: str
    intent: str
    confidence: float
    urgency: str
    entities: Dict[str, List[str]]
    primary_agent: str
    secondary_agents: List[str]
    clarification_required: bool
    routing_reason: str
    agent_trace: List[Dict[str, Any]]
    knowledge_used: bool
    rewritten_queries: List[str]
    escalated: bool
    latency_ms: float


@app.get("/health")
async def health() -> Dict[str, Any]:
    if _orchestrator is None or _knowledge_base is None:
        raise HTTPException(503, "service is not ready")
    return {
        "status": "ok",
        "service": "OpsPilot",
        "agents": _orchestrator.get_stats(),
        "knowledge": _knowledge_base.stats(),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    if _orchestrator is None:
        raise HTTPException(503, "service is not ready")

    history = [message.model_dump() for message in body.history]
    request = Request(
        message=body.message.strip(),
        user_id=body.user_id,
        context=body.context or "",
        history=history or None,
    )
    intent_result = await _orchestrator.classify(request)

    retrieval: Optional[RetrievalResult] = None
    if not intent_result.needs_clarification and _retriever is not None:
        try:
            retrieval = await _retriever.retrieve(body.message, top_k=4)
            request.context = _build_context(body.context, history, retrieval.items)
        except Exception as exc:
            logger.warning("RAG retrieval failed: %s", exc)

    result = await _orchestrator.run(request, intent_result=intent_result)
    if retrieval is not None:
        result.agent_trace.insert(1, {
            "stage": "rag_retrieval",
            "rewritten_queries": retrieval.rewritten_queries,
            "evidence_count": len(retrieval.items),
            "sources": sorted({item["source"] for item in retrieval.items}),
            "reranked": retrieval.reranked,
            "status": "completed",
        })
    routing_step = next(
        (step for step in result.agent_trace if step.get("stage") == "routing"),
        {},
    )
    return ChatResponse(
        request_id=result.request_id,
        response=result.response,
        intent=result.intent.value,
        confidence=result.confidence,
        urgency=result.urgency.value,
        entities=result.entities,
        primary_agent=result.agent_type.value,
        secondary_agents=list(routing_step.get("secondary", [])),
        clarification_required=result.clarification_required,
        routing_reason=result.routing_reason,
        agent_trace=result.agent_trace,
        knowledge_used=bool(retrieval and retrieval.items),
        rewritten_queries=retrieval.rewritten_queries if retrieval else [],
        escalated=result.escalated,
        latency_ms=round(result.latency_ms, 1),
    )


def _build_context(
    caller_context: Optional[str],
    history: List[Dict[str, str]],
    evidence: List[Dict[str, Any]],
) -> str:
    sections: List[str] = []
    if caller_context:
        sections.append(f"[Caller context]\n{caller_context}")
    if history:
        recent = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
        sections.append(f"[Recent conversation]\n{recent}")
    if evidence:
        lines = [
            f"{index}. [{item['source']}] {item['title']}\n{item['content']}"
            for index, item in enumerate(evidence, start=1)
        ]
        sections.append("[Retrieved evidence]\n" + "\n".join(lines))
    return "\n\n".join(sections)


@app.get("/skills", tags=["skills"])
async def skills_summary() -> Dict[str, Any]:
    if _skills is None:
        raise HTTPException(503, "skills are not ready")
    return _skills.summary()


@app.post("/skills/reload", tags=["skills"])
async def reload_skills() -> Dict[str, Any]:
    if _skills is None or _orchestrator is None:
        raise HTTPException(503, "skills are not ready")
    _skills.reload()
    _orchestrator.set_skill_manager(_skills)
    return _skills.summary()


@app.get("/skills/{name}", tags=["skills"])
def skill_detail(name: str) -> Dict[str, Any]:
    if _skills is None:
        raise HTTPException(503, "skills are not ready")
    for skill in _skills.skills:
        if skill.name == name:
            return {**skill.summary(), "content": skill.content}
    raise HTTPException(404, "skill not found")


class DocumentInput(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class DocumentBatch(BaseModel):
    source: Literal["knowledge", "incident"] = "knowledge"
    documents: List[DocumentInput]


@app.post("/knowledge/add", tags=["knowledge"])
async def add_knowledge(body: DocumentBatch) -> Dict[str, Any]:
    if _knowledge_base is None:
        raise HTTPException(503, "knowledge base is not ready")
    count = _knowledge_base.add_documents(
        [document.model_dump() for document in body.documents],
        source=body.source,
    )
    return {"added_chunks": count, "source": body.source, "totals": _knowledge_base.stats()}


@app.post("/knowledge/upload", tags=["knowledge"])
async def upload_knowledge(
    file: UploadFile = File(...),
    source: Literal["knowledge", "incident"] = KNOWLEDGE,
) -> Dict[str, Any]:
    if _knowledge_base is None:
        raise HTTPException(503, "knowledge base is not ready")
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "file exceeds the 10 MB limit")
    filename = file.filename or "untitled.txt"
    if pathlib.Path(filename).suffix.lower() not in {".txt", ".md"}:
        raise HTTPException(400, "only .txt and .md files are supported")
    count = _knowledge_base.add_documents(
        [{"title": pathlib.Path(filename).stem, "content": raw.decode("utf-8", errors="ignore")}],
        source=source,
    )
    return {"added_chunks": count, "source": source, "totals": _knowledge_base.stats()}


@app.get("/knowledge/stats", tags=["knowledge"])
async def knowledge_stats() -> Dict[str, int]:
    if _knowledge_base is None:
        raise HTTPException(503, "knowledge base is not ready")
    return _knowledge_base.stats()


@app.get("/knowledge/documents", tags=["knowledge"])
def knowledge_documents(
    source: Literal["all", "knowledge", "incident"] = "all",
    limit: int = Query(default=100, ge=1, le=200),
) -> Dict[str, Any]:
    if _knowledge_base is None:
        raise HTTPException(503, "knowledge base is not ready")
    return {"items": _knowledge_base.list_documents(source, limit), "totals": _knowledge_base.stats()}


@app.get("/search", tags=["knowledge"])
async def search(query: str, top_k: int = 4) -> Dict[str, Any]:
    if _retriever is None:
        raise HTTPException(503, "retriever is not ready")
    result = await _retriever.retrieve(query, top_k=max(1, min(top_k, 10)))
    return asdict(result)


class IntentEvalInput(BaseModel):
    message: str
    expected_intent: str
    expect_clarification: bool = False


@app.get("/eval/latest", tags=["evaluation"])
def latest_evaluation() -> Dict[str, Any]:
    """Expose the saved evaluation without triggering new model calls."""
    report_path = pathlib.Path(os.getenv(
        "EVAL_BASELINE_PATH", str(ROOT / "data" / "eval" / "opspilot_baseline.json"),
    ))
    if not report_path.is_file():
        raise HTTPException(404, "no saved evaluation report")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("results"), list):
            raise ValueError("invalid report")
        return report
    except (OSError, ValueError) as exc:
        logger.warning("Cannot read saved evaluation: %s", type(exc).__name__)
        raise HTTPException(503, "evaluation report is unavailable") from exc


class RoutingEvalInput(BaseModel):
    message: str
    intent: str
    expected_primary: str
    expected_secondary: List[str] = Field(default_factory=list)
    entities: Dict[str, List[str]] = Field(default_factory=dict)


class RetrievalEvalInput(BaseModel):
    query: str
    expected_titles: List[str]
    top_k: int = Field(default=4, ge=1, le=10)


class DialogEvalInput(BaseModel):
    question: str
    expected_primary: Optional[str] = None
    min_overall: float = Field(default=0.75, ge=0.0, le=1.0)


class EvalRunInput(BaseModel):
    full_dataset: bool = False
    intent_cases: Optional[List[IntentEvalInput]] = None
    routing_cases: Optional[List[RoutingEvalInput]] = None
    retrieval_cases: Optional[List[RetrievalEvalInput]] = None
    dialog_cases: Optional[List[DialogEvalInput]] = None


@app.post("/eval/run", tags=["evaluation"])
async def run_evaluation(body: Optional[EvalRunInput] = None) -> Dict[str, Any]:
    if _evaluator is None:
        raise HTTPException(503, "evaluator is not ready")
    intent_cases = None
    routing_cases = None
    retrieval_cases = None
    dialog_cases = None
    full_dataset = False
    if body:
        full_dataset = body.full_dataset
        if body.intent_cases is not None:
            intent_cases = [IntentTestCase(**case.model_dump()) for case in body.intent_cases]
        if body.routing_cases is not None:
            routing_cases = [RoutingTestCase(**case.model_dump()) for case in body.routing_cases]
        if body.retrieval_cases is not None:
            retrieval_cases = [RetrievalTestCase(**case.model_dump()) for case in body.retrieval_cases]
        if body.dialog_cases is not None:
            dialog_cases = [DialogTestCase(**case.model_dump()) for case in body.dialog_cases]
    report = await _evaluator.run(
        intent_cases=intent_cases,
        routing_cases=routing_cases,
        retrieval_cases=retrieval_cases,
        dialog_cases=dialog_cases,
        full_dataset=full_dataset,
    )
    return asdict(report)


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("APP_ENV") == "development",
    )
