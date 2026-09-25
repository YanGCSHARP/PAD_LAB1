"""HTTP API + веб-интерфейс (Blazor WebAssembly).

    python -m uvicorn src.api.app:app --port 8000     →  http://localhost:8000

Индекс (chunking + embedding) фиксируется при старте по configs/default.yaml;
остальные параметры (Top-K, reranker, пороги, фильтры, LLM, промпт) можно
менять в каждом запросе — это позволяет сравнивать режимы прямо в UI.
"""
from __future__ import annotations

import copy
import mimetypes
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import ROOT, load_config
from src.generation import build_llm, generate
from src.generation.prompts import PROMPTS, REFUSAL
from src.pipeline import RAGPipeline, collection_name
from src.reranking import RERANKERS

app = FastAPI(title="Dota 2 RAG API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CFG = load_config()
LLM_CHOICES = ["groq:openai/gpt-oss-120b", "groq:qwen/qwen3.8-27b", "groq:openai/gpt-oss-20b",
               "gemini:gemini-3.8-flash"]
_state: dict = {}


def rag() -> RAGPipeline:
    if "rag" not in _state:
        _state["rag"] = RAGPipeline(CFG, with_llm=False)
    return _state["rag"]


def llm(choice: str):
    if choice not in _state.setdefault("llms", {}):
        provider, model = choice.split(":", 1)
        _state["llms"][choice] = build_llm(CFG, provider=provider, model=model)
    return _state["llms"][choice]


class Filters(BaseModel):
    source: list[str] = []            # official / fandom
    entity_type: list[str] = []       # hero / item / patch / mechanic


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    top_k: int = Field(20, ge=1, le=50)
    reranker: str = "mminilm"         # none / mminilm / bge-m3
    top_n: int = Field(5, ge=1, le=20)
    score_threshold: float = 0.0
    rerank_threshold: float = 0.0
    filters: Filters = Filters()
    llm: str = LLM_CHOICES[0]
    prompt: str = "strict"


@app.on_event("startup")
def _warmup() -> None:
    rag()


@app.get("/api/health")
def health():
    return {"status": "ok", "index": collection_name(CFG), "chunks": len(rag().chunks)}


@app.get("/api/options")
def options():
    return {"index": collection_name(CFG), "llms": LLM_CHOICES, "prompts": list(PROMPTS),
            "rerankers": ["none", *RERANKERS], "sources": ["official", "fandom"],
            "entity_types": ["hero", "item", "patch", "mechanic"],
            "defaults": AskRequest(question="..").model_dump(exclude={"question"})}


@app.post("/api/ask")
def ask(req: AskRequest):
    if req.prompt not in PROMPTS or req.llm not in LLM_CHOICES:
        raise HTTPException(400, "неизвестный промпт или модель")
    cfg = copy.deepcopy(CFG)
    cfg["retrieval"].update(top_k=req.top_k, filters=req.filters.model_dump())
    cfg["filtering"].update(score_threshold=req.score_threshold)
    cfg["reranker"].update(enabled=req.reranker != "none", model=req.reranker if req.reranker != "none" else "mminilm",
                           top_n=req.top_n, min_score=req.rerank_threshold)
    cfg["generation"].update(prompt=req.prompt)

    res = rag().retrieve(req.question, cfg)
    t0 = time.perf_counter()
    try:
        answer = generate(llm(req.llm), req.prompt, req.question, res.final)
    except Exception as e:                                   # лимит API и т.п. — показываем в UI
        raise HTTPException(502, f"ошибка LLM: {e}") from e
    res.timings["generate"] = time.perf_counter() - t0

    final_ids = {h.chunk.chunk_id for h in res.final}
    return {
        "answer": answer.text, "refused": answer.refused, "sources": answer.sources,
        "context": [{"n": i, "title": h.chunk.title, "section": h.chunk.section, "url": h.chunk.url,
                     "source": h.chunk.source, "entity_type": h.chunk.entity_type,
                     "dense_score": h.dense_score, "rerank_score": h.rerank_score, "text": h.chunk.text}
                    for i, h in enumerate(res.final, 1)],
        "dropped": [{"title": h.chunk.title, "section": h.chunk.section, "dense_score": h.dense_score,
                     "rerank_score": h.rerank_score}
                    for h in res.candidates if h.chunk.chunk_id not in final_ids][:15],
        "filter_log": res.filter_log, "timings": {k: round(v, 3) for k, v in res.timings.items()},
        "llm": req.llm, "tokens": {"prompt": answer.llm.prompt_tokens, "completion": answer.llm.completion_tokens}
        if answer.llm else None, "refusal_text": REFUSAL,
    }


# Blazor WebAssembly UI (ui/RagLab.Web → dotnet publish -c Release -o ui/dist).
# Монтируется последним, чтобы не перекрывать /api/*.
UI_DIR = ROOT / "ui" / "dist" / "wwwroot"
mimetypes.add_type("application/wasm", ".wasm")
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
