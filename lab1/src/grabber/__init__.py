"""Автоматический сбор документов из источников (официальный сайт Dota 2, Fandom Wiki)."""
from __future__ import annotations

from src import config
from src.grabber.base import run_source
from src.grabber.dota_official import DotaOfficialSource
from src.grabber.fandom import FandomSource
from src.grabber.http import HttpClient
from src.grabber.manifest import Manifest


def build_sources(cfg: dict) -> list:
    g = cfg["grabber"]
    raw_dir = config.path(cfg, "raw")
    sources = []
    if g["official"].get("enabled", True):
        http = HttpClient(g["user_agent"], g["request_delay_sec"], g["timeout_sec"], g["max_retries"])
        sources.append(DotaOfficialSource(http, raw_dir, g["official"]))
    if g["fandom"].get("enabled", True):
        http = HttpClient(g["user_agent"], g["request_delay_sec"], g["timeout_sec"], g["max_retries"])
        sources.append(FandomSource(http, raw_dir, g["fandom"], g["official"]["base_url"].rstrip("/")))
    return sources


def grab(cfg: dict, only: str | None = None, force: bool = False, limit: int | None = None,
         reparse: bool = False) -> dict:
    manifest = Manifest(config.path(cfg, "manifest"))
    docs_dir = config.path(cfg, "documents")
    docs_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for src in build_sources(cfg):
        if only and src.name != only:
            continue
        results[src.name] = dict(run_source(src, manifest, docs_dir, force=force, limit=limit, reparse=reparse))
    results["_summary"] = manifest.summary()
    return results
