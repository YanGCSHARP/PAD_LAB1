"""Эксперименты с генерацией: LLM × промпт (+ порог reranker'а как «ворота» отказа).

Retrieval-конфигурация берётся лучшая из run_retrieval.py (best_config.json).
Каждый ответ оценивает судья (Gemini, другое семейство моделей) по correctness,
faithfulness и relevancy (1–5); отказы проверяются правилом.

    python experiments/run_generation.py
    python experiments/run_generation.py --only gpt-oss-120b/strict
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_config, merged  # noqa: E402
from src.evaluation import load_questions  # noqa: E402
from src.evaluation.runner import eval_generation  # noqa: E402
from src.evaluation.table import avg, fmt_table, read_csv, write_csv  # noqa: E402
from src.generation import is_refusal  # noqa: E402
from src.generation.llm import build_llm  # noqa: E402
from src.pipeline import RAGPipeline  # noqa: E402

RES = ROOT / "experiments" / "results"

VARIANTS = [
    # (метка, модель Groq, промпт, порог reranker'а)
    ("gpt-oss-120b/strict", "openai/gpt-oss-120b", "strict", 0.0),
    ("gpt-oss-120b/basic", "openai/gpt-oss-120b", "basic", 0.0),
    ("qwen3.8-27b/strict", "qwen/qwen3.8-27b", "strict", 0.0),
    ("qwen3.8-27b/basic", "qwen/qwen3.8-27b", "basic", 0.0),
    ("gpt-oss-120b/strict+gate", "openai/gpt-oss-120b", "strict", None),   # порог из S7
]


def best_cfg(base: dict) -> dict:
    st = json.loads((RES / "best_config.json").read_text(encoding="utf-8"))
    rr = st.get("reranker", {"model": "mminilm", "candidates_k": 20})
    return merged(base,
                  chunking=st["chunking"], embedding={"model": st["embedding"]},
                  retrieval={"mode": st["mode"], "top_k": rr["candidates_k"], "filters": {}},
                  reranker={"enabled": rr["model"] != "none", "model": rr["model"] if rr["model"] != "none" else "mminilm",
                            "top_n": 5, "min_score": 0.0},
                  filtering={"score_threshold": 0.0, "min_chars": 60, "dedup": True, "max_per_doc": 0})


def main(only: str | None) -> None:
    base = load_config()
    cfg = best_cfg(base)
    gate = json.loads((RES / "best_config.json").read_text(encoding="utf-8")).get("rerank_gate", 0.1)
    qs = load_questions(base)
    rag = RAGPipeline(cfg, with_llm=False)
    judge = build_llm(base, "judge")

    all_rows: list[dict] = []
    for tag, model, prompt, thr in VARIANTS:
        if only and tag != only:
            continue
        c = merged(cfg, generation={"model": model, "prompt": prompt},
                   reranker={"min_score": gate if thr is None else thr})
        llm = build_llm(c, "generation", model=model)
        rows = eval_generation(rag, qs, llm, judge, c, tag=tag)
        write_csv(RES / f"generation_{tag.replace('/', '_').replace('+', '_')}.csv", rows)
        all_rows += rows

    if not all_rows:
        return
    summarize(all_rows, save=not only)


def summarize(all_rows: list[dict], save: bool = True) -> None:
    summary = []
    for tag, *_ in VARIANTS:
        rows = [r for r in all_rows if r["tag"] == tag]
        if not rows:
            continue
        ans = [r for r in rows if r["answerable"]]
        una = [r for r in rows if not r["answerable"]]
        summary.append({
            "tag": tag,
            "correctness": avg(ans, "correctness"),
            "faithfulness": avg(rows, "faithfulness"),
            "relevancy": avg(ans, "relevancy"),
            "answered_ok": avg(ans, "refusal_correct"),        # не отказался, когда ответ есть
            "refused_ok": avg(una, "refusal_correct"),         # отказался, когда ответа нет
            "cited_share": avg(ans, "cited"),
            "latency": avg(rows, "latency"),
            "prompt_tokens": avg(rows, "prompt_tokens"),
        })
    print(fmt_table(summary))
    if save:
        write_csv(RES / "generation_summary.csv", summary)
        write_csv(RES / "generation_all.csv", all_rows)


def resummarize() -> None:
    """Пересчитать сводку по сохранённым ответам (без запросов к API),
    например после уточнения детектора отказов."""
    rows = read_csv(RES / "generation_all.csv")
    for r in rows:
        r["refused"] = is_refusal(str(r["answer"]))
        r["refusal_correct"] = r["refused"] != r["answerable"]
    summarize(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--resummarize", action="store_true", help="пересчитать сводку без запросов к API")
    a = ap.parse_args()
    resummarize() if a.resummarize else main(a.only)
