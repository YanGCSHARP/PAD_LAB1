"""Заранее строит chunks + эмбеддинги + коллекции Qdrant для сетки экспериментов.

Векторизация на CPU — самая долгая часть (~15 chunks/s для e5-small на ноутбуке),
а эмбеддинги кэшируются по хешу текста, поэтому сами эксперименты потом идут быстро.

    python experiments/prebuild.py grid                  # сетка chunking (S1–S3) на e5-small
    python experiments/prebuild.py models section 256    # все embedding-модели для одной стратегии
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config, merged  # noqa: E402
from src.pipeline import build_index, collection_name  # noqa: E402


def build(cfg: dict) -> None:
    t0 = time.perf_counter()
    index, _, chunks = build_index(cfg)
    print(f"{collection_name(cfg)}: {len(chunks)} chunks, {time.perf_counter() - t0:.0f}s", flush=True)


def main() -> None:
    base = load_config()
    what = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if what == "grid":
        configs = []
        for size in (256, 512, 128):
            for strategy in ("section", "paragraph", "fixed"):
                configs.append({"strategy": strategy, "size": size, "overlap": 0, "prefix_title": True})
        for ov in (32, 64, 128):
            configs.append({"strategy": "fixed", "size": 256, "overlap": ov, "prefix_title": True})
        for ch in configs:
            build(merged(base, chunking=ch, embedding={"model": "e5-small"}))
    else:
        strategy, size = sys.argv[2], int(sys.argv[3])
        ch = {"strategy": strategy, "size": size, "overlap": int(sys.argv[4]) if len(sys.argv) > 4 else 0,
              "prefix_title": True}
        for model in ("minilm", "e5-base", "bge-m3"):
            build(merged(base, chunking=ch, embedding={"model": model}))


if __name__ == "__main__":
    main()
