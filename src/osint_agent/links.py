from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .memory import OsintMemory


@dataclass(slots=True)
class LinkResult:
    source_page: str
    url: str
    text: str
    is_pdf: bool
    source: str = "link"
    pointer_score: int = 0
    pointer_reason: str = ""
    trail_depth: int = 0
    trail_score: float = 0.0
    trail_strayed: bool = False


def discover_links(page_url: str, max_links: int = 20, memory: OsintMemory | None = None) -> list[LinkResult]:
    if memory is not None:
        cached = memory.get_link_cache(page_url)
        if cached is not None:
            return [LinkResult(**item) for item in cached]

    response = requests.get(
        page_url,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (OSINT Agent)"},
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    seen: set[str] = set()
    results: list[LinkResult] = []

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        lowered = href.lower()
        if lowered.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue

        resolved = urljoin(page_url, href)
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"}:
            continue

        normalized = parsed._replace(fragment="").geturl()
        if normalized in seen:
            continue

        text = " ".join(anchor.get_text(" ", strip=True).split())
        is_pdf = _looks_like_pdf(normalized, text)
        results.append(
            LinkResult(
                source_page=page_url,
                url=normalized,
                text=text,
                is_pdf=is_pdf,
            )
        )
        seen.add(normalized)
        if len(results) >= max_links:
            break

    if memory is not None:
        memory.set_link_cache(page_url, [result_to_dict(result) for result in results])

    return results


def _looks_like_pdf(url: str, text: str) -> bool:
    lowered = url.lower()
    return lowered.endswith(".pdf") or "/pdf" in lowered or "pdf" in text.lower()


def result_to_dict(result: LinkResult) -> dict[str, Any]:
    return {
        "source": result.source,
        "source_page": result.source_page,
        "url": result.url,
        "text": result.text,
        "is_pdf": str(result.is_pdf),
        "pointer_score": str(result.pointer_score),
        "pointer_reason": result.pointer_reason,
        "trail_depth": str(result.trail_depth),
        "trail_score": str(result.trail_score),
        "trail_strayed": str(result.trail_strayed),
    }