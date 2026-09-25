"""Графики по результатам экспериментов → experiments/figures/*.svg

    python experiments/make_figures.py
    python experiments/export_png.py      # (опционально) SVG → PNG через браузер, для .docx
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from svgchart import Chart  # noqa: E402

from src.evaluation.table import read_csv  # noqa: E402

RES, FIG = ROOT / "results", ROOT / "figures"
FIG.mkdir(exist_ok=True)


def pick(rows, **kw):
    for r in rows:
        if all(r.get(k) == v for k, v in kw.items()):
            return r
    return {}


def fig_chunking():
    rows = read_csv(RES / "retrieval_s1_chunking.csv")
    if not rows:
        return
    sizes = sorted({r["size"] for r in rows})
    for metric, title in (("mrr", "MRR"), ("hit@5", "Hit@5")):
        series = {s: [pick(rows, strategy=s, size=z).get(metric, float("nan")) for z in sizes]
                  for s in ("fixed", "paragraph", "section")}
        Chart(f"S1. {title}: стратегия × размер chunk", 640, 330,
              "e5-small, dense-поиск, 34 отвечаемых вопроса").bars(
            [f"{z} токенов" for z in sizes], series, ymax=1).save(FIG / f"s1_chunking_{metric.replace('@', '')}.svg")


def fig_overlap():
    rows = read_csv(RES / "retrieval_s2_overlap.csv")
    if not rows:
        return
    Chart(f"S2. Fixed-{rows[0]['size']}: влияние overlap", 560, 320, "e5-small, dense-поиск").lines(
        [r["overlap_pct"] for r in rows], {"MRR": [r["mrr"] for r in rows], "Recall@5": [r["recall@5"] for r in rows]},
        ymax=1, xfmt="{}%", xlabel="перекрытие, % от размера chunk").save(FIG / "s2_overlap.svg")


def fig_title():
    rows = read_csv(RES / "retrieval_s3_title.csv")
    if not rows:
        return
    metrics = ["hit@1", "hit@5", "mrr", "recall@5"]
    Chart("S3. Заголовок «Документ — Секция» в начале chunk", 560, 320).bars(
        metrics, {("с заголовком" if r["prefix_title"] else "без заголовка"): [r[m] for m in metrics]
                  for r in sorted(rows, key=lambda r: r["prefix_title"])}, ymax=1).save(FIG / "s3_title.svg")


def fig_embeddings():
    rows = read_csv(RES / "retrieval_s4_embeddings.csv")
    if not rows:
        return
    models = list(dict.fromkeys(r["embedding"] for r in rows))
    Chart("S4. MRR: embedding-модель × язык вопроса", 640, 330, "корпус: RU (dota2.com) + EN (Fandom)").bars(
        models, {"вопрос на русском": [pick(rows, embedding=m, query_lang="ru")["mrr"] for m in models],
                 "вопрос на английском": [pick(rows, embedding=m, query_lang="en")["mrr"] for m in models]},
        ymax=1).save(FIG / "s4_embeddings_mrr.svg")
    Chart("S4. Цена модели: построение индекса на CPU", 560, 300, "секунды, ноутбук Ryzen 5 220 без GPU").bars(
        models, {"время, с": [pick(rows, embedding=m, query_lang="ru")["build_sec"] for m in models]},
        vfmt="{:.0f}", yfmt="{:.0f}").save(FIG / "s4_embeddings_time.svg")


def fig_mode():
    rows = read_csv(RES / "retrieval_s5_mode.csv")
    if not rows:
        return
    metrics = ["hit@1", "hit@5", "mrr", "recall@10"]
    Chart("S5. Dense vs BM25 vs Hybrid (RRF)", 620, 320).bars(
        metrics, {r["mode"]: [r[m] for m in metrics] for r in rows}, ymax=1).save(FIG / "s5_mode.svg")
    state = json.loads((RES / "best_config.json").read_text(encoding="utf-8"))
    row = pick(rows, mode=state.get("mode", "dense"))
    ks = [1, 3, 5, 10, 20]
    Chart(f"Top-K: полнота и точность поиска ({row['mode']})", 560, 320).lines(
        ks, {"Recall@K": [row[f"recall@{k}"] for k in ks],
             "Hit@K": [row[f"hit@{k}"] for k in ks]},
        ymax=1, xlabel="K — число найденных chunks").save(FIG / "topk.svg")


def fig_reranker():
    rows = read_csv(RES / "retrieval_s6_reranker.csv")
    if not rows:
        return
    labels = ["без reranker" if r["reranker"] == "none" else f"{r['reranker']}\nиз top-{r['candidates_k']}" for r in rows]
    metrics = [("hit@1", "Hit@1"), ("mrr", "MRR"), ("ndcg@5", "nDCG@5")]
    Chart("S6. Итоговый контекст (top-5): reranker", 760, 340, "метрики на 5 chunks, которые уходят в LLM").bars(
        labels, {t: [r[m] for r in rows] for m, t in metrics}, ymax=1).save(FIG / "s6_reranker.svg")
    Chart("S6. Задержка поиска на вопрос", 760, 300, "секунды, CPU").bars(
        labels, {"задержка, с": [r["latency"] for r in rows]}, yfmt="{:.1f}").save(FIG / "s6_latency.svg")


def fig_thresholds():
    rows = read_csv(RES / "retrieval_s7_thresholds.csv")
    if not rows:
        return
    for kind, title in (("dense", "cosine similarity"), ("rerank", "reranker")):
        d = [r for r in rows if r["kind"] == kind]
        Chart(f"S7. Порог {title}: отвечаемые vs неотвечаемые", 600, 320).lines(
            [r["threshold"] for r in d],
            {"отвечаемые: контекст сохранён": [r["answerable_kept"] for r in d],
             "неотвечаемые: отсечены": [r["unanswerable_blocked"] for r in d]},
            ymax=1, xfmt="{}", xlabel="порог", end_labels=False).save(FIG / f"s7_threshold_{kind}.svg")


def fig_generation():
    rows = read_csv(RES / "generation_summary.csv")
    if not rows:
        return
    tags = [r["tag"].replace("/", "\n") for r in rows]
    Chart("Генерация: оценка судьи (1–5)", 760, 340, "судья — Gemini; 34 отвечаемых + 7 неотвечаемых вопросов").bars(
        tags, {"correctness": [r["correctness"] for r in rows], "faithfulness": [r["faithfulness"] for r in rows],
               "relevancy": [r["relevancy"] for r in rows]}, ymax=5, vfmt="{:.1f}").save(FIG / "generation_judge.svg")
    Chart("Генерация: поведение при отказе", 760, 320).bars(
        tags, {"ответил, когда ответ есть": [r["answered_ok"] for r in rows],
               "отказал, когда ответа нет": [r["refused_ok"] for r in rows]}, ymax=1).save(FIG / "generation_refusal.svg")


if __name__ == "__main__":
    for f in (fig_chunking, fig_overlap, fig_title, fig_embeddings, fig_mode, fig_reranker, fig_thresholds,
              fig_generation):
        try:
            f()
        except Exception as e:           # один сломанный график не должен мешать остальным
            print("ERROR", f.__name__, repr(e), file=sys.stderr)
