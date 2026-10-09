"""Трассировка запросов в Langfuse (LLM observability).

Включается сама, если в .env есть LANGFUSE_PUBLIC_KEY и LANGFUSE_SECRET_KEY
(и LANGFUSE_HOST, по умолчанию https://cloud.langfuse.com). Без ключей все
функции — пустые обёртки, pipeline работает как раньше.

Каждый вопрос (веб-интерфейс, CLI) — один трейс с дочерними наблюдениями:
retrieve → filter → rerank → llm (generation: промпт, ответ, токены, время).
Вложенные span'ы создаются только внутри трейса, поэтому прогоны
экспериментов (сотни вызовов retrieve/generate) в Langfuse не попадают.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import os

from dotenv import dotenv_values

from src.config import ENV_FILES

log = logging.getLogger(__name__)

_client = None
_initialized = False
_in_trace = contextvars.ContextVar("langfuse_in_trace", default=False)


def client():
    """Клиент Langfuse или None, если ключей нет."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    for env_file in ENV_FILES:
        if env_file.exists():
            for k, v in dotenv_values(env_file).items():
                if k and k.startswith("LANGFUSE_") and v:
                    os.environ.setdefault(k, v.strip())
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import Langfuse
        _client = Langfuse()
    except Exception as e:                       # трассировка не должна ломать систему
        log.warning("Langfuse не инициализирован: %s", e)
        _client = None
    return _client


def enabled() -> bool:
    return client() is not None


@contextlib.contextmanager
def trace(name: str, input=None, metadata=None, flush: bool = False):
    """Корневое наблюдение — один трейс на вопрос пользователя."""
    c = client()
    if c is None:
        yield None
        return
    token = _in_trace.set(True)
    try:
        with c.start_as_current_observation(name=name, as_type="chain", input=input, metadata=metadata) as obs:
            yield obs
    finally:
        _in_trace.reset(token)
        if flush:                                # CLI: отправить до выхода из процесса
            c.flush()


@contextlib.contextmanager
def span(name: str, as_type: str = "span", **kwargs):
    """Дочернее наблюдение; вне трейса ничего не делает."""
    c = client()
    if c is None or not _in_trace.get():
        yield None
        return
    with c.start_as_current_observation(name=name, as_type=as_type, **kwargs) as obs:
        yield obs


def update(obs, **kwargs) -> None:
    if obs is not None:
        obs.update(**kwargs)


def current_trace_url() -> str | None:
    c = client()
    if c is None:
        return None
    try:
        return c.get_trace_url()
    except Exception:
        return None


def hits_view(hits) -> list[dict]:
    """Компактное представление найденных фрагментов для трейса."""
    return [{"rank": i, "title": h.chunk.title, "section": h.chunk.section, "source": h.chunk.source,
             "dense": None if h.dense_score is None else round(h.dense_score, 4),
             "rerank": None if h.rerank_score is None else round(h.rerank_score, 4),
             "chunk_id": h.chunk.chunk_id}
            for i, h in enumerate(hits, 1)]
