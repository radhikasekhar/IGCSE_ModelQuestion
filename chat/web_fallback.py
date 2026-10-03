"""Tavily web search, used only when the ingested documents don't cover a question."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from tavily import TavilyClient

import config


@lru_cache(maxsize=1)
def _client() -> TavilyClient:
    if not config.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not set, so web search is unavailable. Add it to the .env file.")
    return TavilyClient(api_key=config.TAVILY_API_KEY)


def search(query: str, subject: str | None = None, max_results: int = 5) -> list[dict[str, Any]]:
    """Return [{title, url, content}] for the query, scoped to IGCSE level."""
    q = f"IGCSE {subject + ' ' if subject else ''}{query}"
    resp = _client().search(q, search_depth="advanced", max_results=max_results, topic="general")
    return [
        {"title": r.get("title") or r.get("url"), "url": r.get("url"), "content": (r.get("content") or "")[:2500]}
        for r in resp.get("results", [])
        if r.get("url")
    ]
