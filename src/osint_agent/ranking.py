from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .archive import ArchiveResult
from .links import LinkResult
from .learning import rank_with_model
from .pdfs import PdfDocument
from .memory import OsintMemory
from .search import WebResult


@dataclass(slots=True)
class RankedSource:
    kind: str
    score: int
    title: str
    url: str
    reason: str
    source: str
    learned_score: float = 0.0
    heuristic_score: int = 0
    trail_depth: int = 0
    trail_score: float = 0.0
    trail_strayed: bool = False
    path_confidence: float = 0.0
    drift_score: float = 0.0


def rank_sources(
    subject: str,
    web_results: list[WebResult],
    archive_results: list[ArchiveResult],
    pdf_documents: list[PdfDocument],
    discovered_links: list[LinkResult],
    memory: OsintMemory | None = None,
) -> list[RankedSource]:
    items: list[RankedSource] = []

    for result in web_results:
        items.append(_rank_web_source(subject, result))
    for result in archive_results:
        items.append(_rank_archive_source(subject, result))
    for document in pdf_documents:
        items.append(_rank_pdf_source(subject, document))
    for link in discovered_links:
        if link.is_pdf:
            items.append(_rank_linked_pdf(subject, link))
        else:
            items.append(_rank_link_source(subject, link))

    items = rank_with_model(subject, items, memory=memory)
    return sorted(items, key=lambda item: item.score, reverse=True)


def _rank_web_source(subject: str, result: WebResult) -> RankedSource:
    score, reasons = _base_rank(subject, result.title, result.url, result.snippet, base=40)
    host = urlparse(result.url).hostname or ""
    if host.endswith((".gov", ".edu", ".mil")):
        score += 12
        reasons.append("official domain bonus")
    return RankedSource("web", min(score, 100), result.title or result.url, result.url, "; ".join(reasons), result.source, heuristic_score=min(score, 100))


def _rank_archive_source(subject: str, result: ArchiveResult) -> RankedSource:
    score, reasons = _base_rank(subject, result.title, result.url, result.description, base=50)
    if result.mediatype:
        score += 4
        reasons.append("archived record bonus")
    score += 3 if result.identifier else 0
    if result.identifier:
        reasons.append("stable archive identifier")
    return RankedSource("archive", min(score, 100), result.title or result.identifier, result.url, "; ".join(reasons), result.source, heuristic_score=min(score, 100))


def _rank_pdf_source(subject: str, document: PdfDocument) -> RankedSource:
    title = document.source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    score, reasons = _base_rank(subject, title, document.source, document.text, base=60)
    score += min(15, len(document.text) // 1000)
    reasons.append("extracted text bonus")
    return RankedSource("pdf", min(score, 100), title, document.source, "; ".join(reasons), "pdf", heuristic_score=min(score, 100))


def _rank_linked_pdf(subject: str, link: LinkResult) -> RankedSource:
    score, reasons = _base_rank(subject, link.text or link.url, link.url, link.text, base=65)
    score += 5
    reasons.append("discovered PDF link bonus")
    pointer_bonus = int(getattr(link, "pointer_score", 0) or 0)
    if pointer_bonus:
        score += min(pointer_bonus, 12)
        reasons.append(f"pointer trail bonus +{min(pointer_bonus, 12)}")
    path_confidence, drift_score = _trail_metrics(link)
    return RankedSource(
        "linked_pdf",
        min(score, 100),
        link.text or link.url,
        link.url,
        "; ".join(reasons),
        link.source,
        heuristic_score=min(score, 100),
        trail_depth=int(getattr(link, "trail_depth", 0) or 0),
        trail_score=float(getattr(link, "trail_score", 0.0) or 0.0),
        trail_strayed=bool(getattr(link, "trail_strayed", False)),
        path_confidence=path_confidence,
        drift_score=drift_score,
    )


def _rank_link_source(subject: str, link: LinkResult) -> RankedSource:
    score, reasons = _base_rank(subject, link.text or link.url, link.url, link.text, base=25)
    pointer_bonus = int(getattr(link, "pointer_score", 0) or 0)
    if pointer_bonus:
        score += min(pointer_bonus, 15)
        reasons.append(f"pointer trail bonus +{min(pointer_bonus, 15)}")
    path_confidence, drift_score = _trail_metrics(link)
    return RankedSource(
        "link",
        min(score, 100),
        link.text or link.url,
        link.url,
        "; ".join(reasons),
        link.source,
        heuristic_score=min(score, 100),
        trail_depth=int(getattr(link, "trail_depth", 0) or 0),
        trail_score=float(getattr(link, "trail_score", 0.0) or 0.0),
        trail_strayed=bool(getattr(link, "trail_strayed", False)),
        path_confidence=path_confidence,
        drift_score=drift_score,
    )


def _base_rank(subject: str, title: str, url: str, text: str, base: int) -> tuple[int, list[str]]:
    score = base
    reasons: list[str] = [f"base {base}"]
    subject_tokens = _subject_tokens(subject)
    haystacks = [title.lower(), url.lower(), text.lower()]

    matches = 0
    for token in subject_tokens:
        if any(token in haystack for haystack in haystacks):
            matches += 1

    if matches:
        bonus = min(18, matches * 4)
        score += bonus
        reasons.append(f"{matches} subject token match(es) +{bonus}")

    if title:
        score += 3
        reasons.append("title present")
    if url:
        score += 2
        reasons.append("url present")

    host = urlparse(url).hostname or ""
    if host.startswith(("www.", "m.")):
        score += 1

    if len(text.strip()) > 250:
        score += 4
        reasons.append("substantial text")
    elif text.strip():
        score += 2
        reasons.append("some supporting text")

    return score, reasons


def _subject_tokens(subject: str) -> list[str]:
    tokens: list[str] = []
    for raw in subject.lower().split():
        token = "".join(char for char in raw if char.isalnum())
        if len(token) >= 3:
            tokens.append(token)
    return tokens


def result_to_dict(result: RankedSource) -> dict[str, Any]:
    return {
        "kind": result.kind,
        "score": str(result.score),
        "title": result.title,
        "url": result.url,
        "reason": result.reason,
        "source": result.source,
        "trail_depth": str(result.trail_depth),
        "trail_score": str(result.trail_score),
        "trail_strayed": str(result.trail_strayed),
        "path_confidence": str(result.path_confidence),
        "drift_score": str(result.drift_score),
    }


def _trail_metrics(item: LinkResult) -> tuple[float, float]:
    trail_score = float(getattr(item, "trail_score", 0.0) or 0.0)
    trail_strayed = bool(getattr(item, "trail_strayed", False))
    path_confidence = max(0.0, min(100.0, trail_score * 5.0))
    drift_score = max(0.0, min(100.0, 100.0 - path_confidence + (20.0 if trail_strayed else 0.0)))
    return path_confidence, drift_score