from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from .links import LinkResult, discover_links
from .memory import OsintMemory
from .pdfs import PdfDocument, extract_pdf_text


@dataclass(slots=True)
class CrawlResult:
    visited_urls: list[str]
    discovered_links: list[LinkResult]
    pdf_documents: list[PdfDocument]
    memory_hits: int
    skipped_domains: list[str]


def crawl_sources(
    seeds: Iterable[str],
    *,
    memory: OsintMemory | None = None,
    subject: str | None = None,
    track_trails: bool = True,
    max_depth: int = 1,
    max_pages: int = 30,
    link_limit: int = 20,
    allow_domains: list[str] | None = None,
    deny_domains: list[str] | None = None,
    trail_depth_bonus: int = 2,
    trail_min_score: int = 3,
) -> CrawlResult:
    queue = deque((seed, 0, seed, 0) for seed in seeds)
    visited: set[str] = set()
    discovered_links: list[LinkResult] = []
    pdf_documents: list[PdfDocument] = []
    memory_hits = 0
    skipped_domains: list[str] = []
    subject_tokens = _subject_tokens(subject or "")

    while queue and len(visited) < max_pages:
        url, depth, parent_url, trail_strength = queue.popleft()
        normalized = _normalize_url(url)
        if not normalized or normalized in visited:
            continue
        if not _domain_allowed(normalized, allow_domains, deny_domains):
            skipped_domains.append(normalized)
            continue

        visited.add(normalized)

        if _looks_like_pdf(normalized):
            if memory is not None:
                cached_pdf = memory.get_pdf_cache(normalized)
                if cached_pdf is not None:
                    memory_hits += 1
                    pdf_documents.append(PdfDocument(source=cached_pdf.source, text=cached_pdf.text, page_count=cached_pdf.page_count))
                    memory.mark_visit(normalized, parent_url, depth, "pdf", Path(normalized).name, "pdf cache hit")
                    continue
            try:
                document = extract_pdf_text(normalized, memory=memory)
                pdf_documents.append(document)
                if memory is not None:
                    memory.mark_visit(normalized, parent_url, depth, "pdf", Path(normalized).name, f"{document.page_count} pages")
            except Exception:
                if memory is not None:
                    memory.mark_visit(normalized, parent_url, depth, "pdf", Path(normalized).name, "pdf fetch failed")
            continue

        try:
            cached_links = memory.get_link_cache(normalized) if memory is not None else None
            if cached_links is not None:
                memory_hits += 1
            links = discover_links(
                normalized,
                max_links=link_limit,
                memory=memory,
            )
        except Exception:
            if memory is not None:
                memory.mark_visit(normalized, parent_url, depth, "page", Path(normalized).name, "page fetch failed")
            continue

        if memory is not None and memory.get_link_cache(normalized) is not None:
            pass

        discovered_links.extend(links)
        if memory is not None:
            memory.mark_visit(normalized, parent_url, depth, "page", Path(normalized).name, f"{len(links)} links")

        for link in links:
            score, reason = _pointer_score(link, subject_tokens)
            propagated = max(score, int(trail_strength * 0.75))
            if score > 0 and trail_strength > 0:
                propagated += 1
            link.pointer_score = propagated
            link.pointer_reason = reason
            link.trail_depth = depth + 1
            link.trail_score = float(propagated)
            link.trail_strayed = propagated < int(trail_min_score) and (depth + 1) > 0

        prioritized_links = sorted(links, key=lambda item: item.pointer_score, reverse=True) if track_trails else links
        max_follow_depth = max_depth + max(0, int(trail_depth_bonus)) if track_trails else max_depth

        for link in prioritized_links:
            next_depth = depth + 1
            if not _domain_allowed(link.url, allow_domains, deny_domains):
                skipped_domains.append(link.url)
                continue
            if next_depth <= max_depth:
                queue.append((link.url, next_depth, normalized, link.pointer_score))
                continue
            if track_trails and next_depth <= max_follow_depth and link.pointer_score >= int(trail_min_score):
                queue.append((link.url, next_depth, normalized, link.pointer_score))

    return CrawlResult(
        visited_urls=list(visited),
        discovered_links=discovered_links,
        pdf_documents=pdf_documents,
        memory_hits=memory_hits,
        skipped_domains=skipped_domains,
    )


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return parsed._replace(fragment="").geturl()


def _looks_like_pdf(url: str) -> bool:
    lowered = url.lower()
    return lowered.endswith(".pdf") or "/pdf" in lowered


def _domain_allowed(url: str, allow_domains: list[str] | None, deny_domains: list[str] | None) -> bool:
    host = urlparse(url).hostname or ""
    if not host:
        return False
    if deny_domains and _matches_any_domain(host, deny_domains):
        return False
    if allow_domains and not _matches_any_domain(host, allow_domains):
        return False
    return True


def _matches_any_domain(host: str, domains: list[str]) -> bool:
    for domain in domains:
        normalized = domain.strip().lower().lstrip(".")
        if not normalized:
            continue
        if host == normalized or host.endswith("." + normalized):
            return True
    return False


def _subject_tokens(subject: str) -> list[str]:
    tokens: list[str] = []
    for raw in subject.lower().split():
        token = "".join(char for char in raw if char.isalnum())
        if len(token) >= 3:
            tokens.append(token)
    return tokens


def _pointer_score(link: LinkResult, subject_tokens: list[str]) -> tuple[int, str]:
    if not subject_tokens:
        return 0, ""

    pointer_keywords = (
        "about",
        "bio",
        "profile",
        "team",
        "staff",
        "contact",
        "press",
        "news",
        "reference",
        "source",
        "archive",
        "mirror",
        "cached",
        "snapshot",
        "dossier",
        "report",
    )

    haystack = f"{link.text} {link.url}".lower()
    token_hits = sum(1 for token in subject_tokens if token in haystack)
    keyword_hits = sum(1 for keyword in pointer_keywords if keyword in haystack)
    score = (token_hits * 3) + min(keyword_hits, 3)
    if link.is_pdf and token_hits:
        score += 2
    reason_parts = []
    if token_hits:
        reason_parts.append(f"token hits={token_hits}")
    if keyword_hits:
        reason_parts.append(f"pointer terms={keyword_hits}")
    if link.is_pdf and token_hits:
        reason_parts.append("pdf bonus")
    return score, ", ".join(reason_parts)