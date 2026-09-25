"""Эксперименты с поиском (без LLM): chunking → overlap → заголовок → embeddings →
язык запроса → режим поиска → Top-K → reranker → пороги фильтрации.

Этапы последовательные: лучший вариант этапа (по MRR, затем Recall@5) фиксируется
и используется дальше. Результаты: experiments/results/retrieval_<этап>.csv

    python experiments/run_retrieval.py            # все этапы
    python experiments/run_retrieval.py --only s4  # один этап (берёт лучшие из прошлых CSV)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_config, merged  # noqa: E402
from src.evaluation import load_questions  # noqa: E402
from src.evaluation.runner import eval_refusal_gate, eval_retrieval  # noqa: E402
from src.evaluation.table import avg, fmt_table, read_csv, summarize, write_csv  # noqa: E402
from src.pipeline import RAGPipeline  # noqa: E402

RES = ROOT / "experiments" / "results"
RES.mkdir(parents=True, exist_ok=True)
METRICS = ["hit@1", "hit@3", "hit@5", "hit@10", "hit@20", "mrr", "recall@3", "recall@5", "recall@10",
           "recall@20", "precision@5", "ndcg@5", "ndcg@10", "latency"]
STATE = RES / "best_config.json"

# «чистый» поиск: без фильтров и reranker'а, чтобы сравнивать только retriever
RAW = {"filtering": {"score_threshold": 0.0, "min_chars": 0, "dedup": False, "max_per_doc": 0},
       "reranker": {"enabled": False, "top_n": 20}, "retrieval": {"mode": "dense", "top_k": 20, "filters": {}}}


def run(cfg: dict, questions, label: dict, stage="candidates", use_en=False) -> dict:
    t0 = time.perf_counter()
    rag = RAGPipeline(cfg, with_llm=False)
    build = time.perf_counter() - t0
    rows = eval_retrieval(rag, questions, cfg, use_en=use_en, stage=stage)
    row = {**label, "n_chunks": len(rag.chunks),
           "avg_tokens": round(sum(c.n_tokens for c in rag.chunks) / len(rag.chunks), 1),
           "build_sec": round(build, 1), **summarize(rows, METRICS)}
    print(json.dumps(row, ensure_ascii=False))
    return row


def best(rows: list[dict]) -> dict:
    return max(rows, key=lambda r: (round(r["mrr"], 3), r["recall@5"]))


def save(name: str, rows: list[dict]) -> None:
    write_csv(RES / f"retrieval_{name}.csv", rows)
    print(fmt_table(rows))


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main(only: str | None) -> None:
    base = load_config()
    qs = load_questions(base)
    st = load_state()
    st.setdefault("chunking", {"strategy": "section", "size": 256, "overlap": 0, "prefix_title": True})
    st.setdefault("embedding", "e5-small")
    st.setdefault("mode", "dense")
    want = (lambda s: only is None or only == s)

    def cfg_with(**kw):
        c = merged(base, **RAW)
        c = merged(c, chunking=kw.get("chunking", st["chunking"]),
                   embedding={"model": kw.get("embedding", st["embedding"])},
                   retrieval={"mode": kw.get("mode", st["mode"]), "top_k": kw.get("top_k", 20), "filters": {}})
        return c

    # S1: стратегия × размер chunk
    if want("s1"):
        rows = []
        for strategy in ("fixed", "paragraph", "section"):
            for size in (128, 256, 512):
                ch = {"strategy": strategy, "size": size, "overlap": 0, "prefix_title": True}
                rows.append(run(cfg_with(chunking=ch), qs, {"strategy": strategy, "size": size}))
        save("s1_chunking", rows)
        b = best(rows)
        st["chunking"] = {"strategy": b["strategy"], "size": int(b["size"]), "overlap": 0, "prefix_title": True}
        save_state(st)

    # S2: overlap для fixed-окна (размер — лучший из S1)
    if want("s2"):
        size = st["chunking"]["size"]
        rows = []
        for frac in (0, 0.125, 0.25, 0.5):
            ch = {"strategy": "fixed", "size": size, "overlap": int(size * frac), "prefix_title": True}
            rows.append(run(cfg_with(chunking=ch), qs, {"strategy": "fixed", "size": size,
                                                        "overlap": int(size * frac), "overlap_pct": int(frac * 100)}))
        save("s2_overlap", rows)
        b = best(rows)
        s1 = read_csv(RES / "retrieval_s1_chunking.csv")
        s1_best = best(s1) if s1 else None
        if s1_best is None or (b["mrr"], b["recall@5"]) > (s1_best["mrr"], s1_best["recall@5"]):
            st["chunking"] = {"strategy": "fixed", "size": size, "overlap": int(b["overlap"]), "prefix_title": True}
        save_state(st)

    # S3: заголовок-контекст "Документ — Секция" в начале chunk
    if want("s3"):
        rows = []
        for prefix in (False, True):
            ch = {**st["chunking"], "prefix_title": prefix}
            rows.append(run(cfg_with(chunking=ch), qs, {"prefix_title": prefix}))
        save("s3_title", rows)
        st["chunking"]["prefix_title"] = bool(best(rows)["prefix_title"])
        save_state(st)

    # S4: embedding-модели × язык запроса (RU / EN)
    if want("s4"):
        rows = []
        for emb in ("e5-small", "minilm", "e5-base", "bge-m3"):
            for lang in ("ru", "en"):
                rows.append(run(cfg_with(embedding=emb), qs, {"embedding": emb, "query_lang": lang},
                                use_en=lang == "en"))
        save("s4_embeddings", rows)
        st["embedding"] = best([r for r in rows if r["query_lang"] == "ru"])["embedding"]
        save_state(st)

    # S5: dense vs BM25 vs hybrid (RRF)
    if want("s5"):
        rows = [run(cfg_with(mode=m), qs, {"mode": m}) for m in ("dense", "bm25", "hybrid")]
        save("s5_mode", rows)
        st["mode"] = best(rows)["mode"]
        save_state(st)

    # S6: reranker (кандидаты top-K → rerank → top-5), метрики на итоговом контексте
    if want("s6"):
        rows = []
        for rr in (None, "mminilm", "bge-m3"):
            for k in (10, 20, 40):
                if rr is None and k != 20:
                    continue
                c = cfg_with(top_k=k)
                c = merged(c, reranker={"enabled": rr is not None, "model": rr or "mminilm", "top_n": 5})
                rows.append(run(c, qs, {"reranker": rr or "none", "candidates_k": k}, stage="final"))
        save("s6_reranker", rows)
        b = best(rows)
        st["reranker"] = {"model": b["reranker"], "candidates_k": int(b["candidates_k"])}
        save_state(st)

    # S7: пороги фильтрации — отвечаемые vs неотвечаемые вопросы
    if want("s7"):
        rr = st.get("reranker", {"model": "mminilm", "candidates_k": 20})
        c = cfg_with(top_k=rr["candidates_k"])
        c = merged(c, reranker={"enabled": rr["model"] != "none", "model": rr["model"] if rr["model"] != "none" else "mminilm",
                                "top_n": 5, "min_score": 0.0},
                   filtering={"score_threshold": 0.0, "min_chars": 60, "dedup": True, "max_per_doc": 0})
        rag = RAGPipeline(c, with_llm=False)
        scores = eval_refusal_gate(rag, qs, c)
        write_csv(RES / "retrieval_s7_scores.csv", scores)
        ans = [r for r in scores if r["answerable"]]
        una = [r for r in scores if not r["answerable"]]
        for col in ("top_dense", "top_rerank"):
            print(f"{col}: отвечаемые min={min(r[col] for r in ans):.3f} avg={avg(ans, col):.3f}; "
                  f"неотвечаемые max={max(r[col] for r in una):.3f} avg={avg(una, col):.3f}")
        # перебор порогов: доля отвечаемых, которые проходят (и с эталоном в контексте),
        # и доля неотвечаемых, которые отсекаются → максимизируем balanced accuracy
        rows = []
        for kind, col, grid in (("dense", "top_dense", [x / 100 for x in range(70, 92)]),
                                ("rerank", "top_rerank", [0, .01, .02, .05, .1, .15, .2, .3, .4, .5, .6, .7])):
            for t in grid:
                kept = sum(r[col] >= t for r in ans) / len(ans)
                kept_gold = sum(r[col] >= t and r["gold_in_context"] for r in ans) / len(ans)
                blocked = sum(r[col] < t for r in una) / len(una)
                rows.append({"kind": kind, "threshold": t, "answerable_kept": round(kept, 4),
                             "answerable_kept_with_gold": round(kept_gold, 4),
                             "unanswerable_blocked": round(blocked, 4), "balanced_acc": round((kept + blocked) / 2, 4)})
        write_csv(RES / "retrieval_s7_thresholds.csv", rows)
        rr_rows = [r for r in rows if r["kind"] == "rerank"]
        best_rr = max(rr_rows, key=lambda r: (r["balanced_acc"], -r["threshold"]))
        st["rerank_gate"] = best_rr["threshold"]
        save_state(st)
        print(fmt_table(sorted(rows, key=lambda r: -r["balanced_acc"])[:8]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    main(ap.parse_args().only)
