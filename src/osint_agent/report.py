from __future__ import annotations

from datetime import datetime, timezone

from .archive import ArchiveResult
from .crawler import CrawlResult
from .links import LinkResult
from .pdfs import PdfDocument
from .ranking import RankedSource
from .visualize import build_crawl_tree
from .search import WebResult


def _section(title: str) -> str:
    return f"\n## {title}\n"


def _truncate(text: str, limit: int = 400) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def build_markdown_report(
    subject: str,
    web_results: list[WebResult],
    archive_results: list[ArchiveResult],
    pdf_documents: list[PdfDocument],
    crawl_result: CrawlResult | None = None,
    discovered_links: list[LinkResult] | None = None,
    ranked_sources: list[RankedSource] | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# OSINT Research Report: {subject}")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    if ranked_sources:
        lines.append("## Ranked Sources")
        for result in ranked_sources[:15]:
            lines.append(
                f"- [{result.title}]({result.url}) — score {result.score}, path {getattr(result, 'path_confidence', 0.0):.1f}, drift {getattr(result, 'drift_score', 0.0):.1f}"
            )
            lines.append(f"  - {result.reason}")
        lines.append("")
    if crawl_result is not None:
        lines.append(build_crawl_tree(crawl_result))
        lines.append("")
    lines.append("## Executive Notes")
    if web_results:
        lines.append(f"- Web search returned {len(web_results)} candidate sources.")
    else:
        lines.append("- Web search returned no results.")
    if archive_results:
        wayback_count = sum(1 for item in archive_results if getattr(item, "source", "") == "wayback_machine")
        lines.append(f"- Internet Archive returned {len(archive_results)} candidate records.")
        if wayback_count:
            lines.append(f"- Wayback Machine snapshots recovered: {wayback_count}.")
    else:
        lines.append("- Internet Archive returned no results.")
    if pdf_documents:
        lines.append(f"- Extracted text from {len(pdf_documents)} PDF source(s).")
    else:
        lines.append("- No PDFs were supplied.")
    if discovered_links:
        pdf_links = sum(1 for link in discovered_links if link.is_pdf)
        trail_links = sum(1 for link in discovered_links if float(getattr(link, "trail_score", 0.0) or 0.0) > 0)
        stray_links = sum(1 for link in discovered_links if bool(getattr(link, "trail_strayed", False)))
        lines.append(f"- Discovered {len(discovered_links)} outbound link(s), including {pdf_links} PDF link(s).")
        if trail_links:
            lines.append(f"- Trail tracking scored {trail_links} link(s), with {stray_links} marked as stray from the strongest path.")

    if ranked_sources:
        confident_sources = sum(1 for result in ranked_sources if float(getattr(result, "path_confidence", 0.0) or 0.0) >= 60.0)
        drifting_sources = sum(1 for result in ranked_sources if float(getattr(result, "drift_score", 0.0) or 0.0) >= 40.0)
        lines.append(f"- Path confidence judged {confident_sources} source(s) as on-target; {drifting_sources} source(s) look like detours.")

    lines.append(_section("Web Sources"))
    if web_results:
        for result in web_results:
            lines.append(f"- [{result.title}]({result.url})")
            if result.snippet:
                lines.append(f"  - {_truncate(result.snippet)}")
    else:
        lines.append("- No web sources found.")

    lines.append(_section("Internet Archive"))
    if archive_results:
        for result in archive_results:
            label = result.title or result.identifier
            lines.append(f"- [{label}]({result.url})")
            source_name = "Wayback" if result.source == "wayback_machine" else "Internet Archive"
            meta = ", ".join(value for value in [source_name, result.date, result.mediatype] if value)
            if meta:
                lines.append(f"  - {meta}")
            if result.description:
                lines.append(f"  - {_truncate(result.description)}")
    else:
        lines.append("- No archive records found.")

    lines.append(_section("Discovered Links"))
    if discovered_links:
        for link in discovered_links:
            marker = "PDF" if link.is_pdf else "LINK"
            label = link.text or link.url
            trail_note = ""
            trail_score = float(getattr(link, "trail_score", 0.0) or 0.0)
            if trail_score > 0:
                trail_note = f" [trail={trail_score:.1f}{' stray' if getattr(link, 'trail_strayed', False) else ''}]"
            lines.append(f"- [{marker}] {label} -> {link.url}{trail_note}")
            lines.append(f"  - Source page: {link.source_page}")
    else:
        lines.append("- No links were discovered.")

    lines.append(_section("PDF Evidence"))
    if pdf_documents:
        for document in pdf_documents:
            source_label = document.source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            lines.append(f"- {source_label} ({document.page_count} pages)")
            if document.text:
                lines.append(f"  - {_truncate(document.text)}")
            else:
                lines.append("  - No extractable text found.")
    else:
        lines.append("- No PDFs were supplied.")

    lines.append(_section("Confidence Notes"))
    lines.append("- This report is evidence-first. It does not infer facts that are not directly supported by the collected sources.")
    lines.append("- If the subject is ambiguous, rerun with a narrower query and additional source filters.")

    return "\n".join(lines).strip() + "\n"
