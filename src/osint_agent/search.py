from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ddgs import DDGS

from .memory import OsintMemory


@dataclass(slots=True)
class WebResult:
    title: str
    url: str
    snippet: str
    source: str = "web"


def web_search(query: str, max_results: int = 10, memory: OsintMemory | None = None) -> list[WebResult]:
    cache_key = f"{query}|{max_results}"
    if memory is not None:
        cached = memory.get_query_cache("web", cache_key)
        if cached is not None:
            return [WebResult(**item) for item in cached.payload]

    results: list[WebResult] = []

    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            title = str(item.get("title") or "").strip()
            url = str(item.get("href") or item.get("url") or "").strip()
            snippet = str(item.get("body") or item.get("snippet") or "").strip()
            if not title and not url:
                continue
            results.append(WebResult(title=title, url=url, snippet=snippet))

    if memory is not None:
        memory.set_query_cache("web", cache_key, [result_to_dict(result) for result in results])

    return results


def result_to_dict(result: WebResult) -> dict[str, Any]:
    return {
        "source": result.source,
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
    }
