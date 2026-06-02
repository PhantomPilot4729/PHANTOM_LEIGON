from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
from pathlib import Path

from .archive import search_archive, search_wayback_snapshots
from .crawler import CrawlResult, crawl_sources
from .exporting import write_csv, write_json
from .memory import OsintMemory
from .learning import train_model
from .pdfs import PdfDocument, extract_pdf_text
from .ranking import RankedSource, rank_sources
from .report import build_markdown_report
from .search import WebResult, web_search


@dataclass(slots=True)
class InvestigationResult:
    subject: str
    web_results: list[WebResult]
    archive_results: list
    pdf_documents: list[PdfDocument]
    crawl_result: CrawlResult
    ranked_sources: list[RankedSource]
    report: str
    memory_stats: dict[str, int]
    export_payload: dict[str, object]
    learning_stats: dict[str, float | int]


def run_investigation(
    subject: str,
    *,
    pdf_sources: list[str] | None = None,
    web_limit: int = 10,
    archive_limit: int = 10,
    follow_links: bool = True,
    track_trails: bool = True,
    crawl_depth: int = 1,
    max_pages: int = 30,
    link_limit: int = 20,
    allow_domains: list[str] | None = None,
    deny_domains: list[str] | None = None,
    open_crawl: bool = False,
    memory_db: str | Path = ".osint_memory.sqlite3",
    memory: OsintMemory | None = None,
    json_output: str | Path | None = None,
    csv_output: str | Path | None = None,
) -> InvestigationResult:
    owns_memory = memory is None
    memory = memory or OsintMemory(memory_db)
    try:
        web_results = web_search(subject, max_results=web_limit, memory=memory)
        archive_results = search_archive(subject, max_results=archive_limit, memory=memory)
        wayback_results = search_wayback_snapshots([result.url for result in web_results], per_url=2, memory=memory)
        if wayback_results:
            archive_results.extend(wayback_results)

        pdf_documents: list[PdfDocument] = []
        for source in pdf_sources or []:
            pdf_documents.append(extract_pdf_text(source, memory=memory))

        crawl_seed_urls = [result.url for result in web_results] + [result.url for result in archive_results]
        effective_allow_domains = allow_domains or (_seed_domains(crawl_seed_urls) if not open_crawl else None)
        crawl_result = CrawlResult(visited_urls=[], discovered_links=[], pdf_documents=[], memory_hits=0, skipped_domains=[])
        if follow_links and crawl_seed_urls:
            crawl_result = crawl_sources(
                crawl_seed_urls,
                memory=memory,
                subject=subject,
                track_trails=track_trails,
                max_depth=crawl_depth,
                max_pages=max_pages,
                link_limit=link_limit,
                allow_domains=effective_allow_domains,
                deny_domains=deny_domains,
            )

        for document in crawl_result.pdf_documents:
            if document.source not in {item.source for item in pdf_documents}:
                pdf_documents.append(document)

        discovered_links = crawl_result.discovered_links
        ranked_sources = rank_sources(subject, web_results, archive_results, pdf_documents, discovered_links, memory=memory)
        report = build_markdown_report(subject, web_results, archive_results, pdf_documents, crawl_result, discovered_links, ranked_sources)
        memory_stats = memory.stats()
        memory_stats["cache_hits"] = crawl_result.memory_hits

        training_stats, eval_metrics, ck = train_model(memory, epochs=100, lr=0.001)
        learning_stats = {
            "examples": training_stats.examples,
            "epochs": training_stats.epochs,
            "loss": training_stats.loss,
            "ndcg_at_10": eval_metrics.ndcg_at_10,
            "mrr": eval_metrics.mrr,
            "checkpoint": ck,
        }

        export_payload = _build_export_payload(
            subject,
            web_results=web_results,
            archive_results=archive_results,
            pdf_documents=pdf_documents,
            crawl_result=crawl_result,
            ranked_sources=ranked_sources,
            report=report,
            memory_stats=memory_stats,
            learning_stats=learning_stats,
        )

        if json_output is not None:
            write_json(json_output, export_payload)
        if csv_output is not None:
            write_csv(csv_output, _flatten_export_rows(export_payload))

        return InvestigationResult(
            subject=subject,
            web_results=web_results,
            archive_results=archive_results,
            pdf_documents=pdf_documents,
            crawl_result=crawl_result,
            ranked_sources=ranked_sources,
            report=report,
            memory_stats=memory_stats,
            export_payload=export_payload,
            learning_stats=learning_stats,
        )
    finally:
        if owns_memory:
            memory.close()


def _seed_domains(urls: list[str]) -> list[str]:
    domains: list[str] = []
    seen: set[str] = set()
    for url in urls:
        host = _host_for(url)
        if host and host not in seen:
            seen.add(host)
            domains.append(host)
    return domains


def _host_for(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""


def _build_export_payload(
    subject: str,
    *,
    web_results: list[WebResult],
    archive_results: list,
    pdf_documents: list[PdfDocument],
    crawl_result: CrawlResult,
    ranked_sources: list[RankedSource],
    report: str,
    memory_stats: dict[str, int],
    learning_stats: dict[str, float | int] | None = None,
) -> dict[str, object]:
    return {
        "subject": subject,
        "report": report,
        "memory_stats": memory_stats,
        "learning_stats": learning_stats or {},
        "web_results": [asdict(result) for result in web_results],
        "archive_results": [asdict(result) for result in archive_results],
        "pdf_documents": [asdict(result) for result in pdf_documents],
        "crawl_result": {
            "visited_urls": crawl_result.visited_urls,
            "discovered_links": [asdict(result) for result in crawl_result.discovered_links],
            "pdf_documents": [asdict(result) for result in crawl_result.pdf_documents],
            "memory_hits": crawl_result.memory_hits,
            "skipped_domains": crawl_result.skipped_domains,
        },
        "ranked_sources": [asdict(result) for result in ranked_sources],
    }


def _flatten_export_rows(export_payload: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    subject = str(export_payload.get("subject", ""))
    memory_stats = export_payload.get("memory_stats", {})

    for result in export_payload.get("ranked_sources", []):
        row = dict(result)
        row["subject"] = subject
        row["section"] = "ranked_sources"
        rows.append(row)

    for result in export_payload.get("web_results", []):
        row = dict(result)
        row["subject"] = subject
        row["section"] = "web_results"
        rows.append(row)

    for result in export_payload.get("archive_results", []):
        row = dict(result)
        row["subject"] = subject
        row["section"] = "archive_results"
        rows.append(row)

    for result in export_payload.get("pdf_documents", []):
        row = dict(result)
        row["subject"] = subject
        row["section"] = "pdf_documents"
        rows.append(row)

    crawl_result = export_payload.get("crawl_result", {})
    for result in crawl_result.get("discovered_links", []):
        row = dict(result)
        row["subject"] = subject
        row["section"] = "discovered_links"
        rows.append(row)

    rows.append({"subject": subject, "section": "memory_stats", **dict(memory_stats)})
    rows.append({"subject": subject, "section": "learning_stats", **dict(export_payload.get("learning_stats", {}))})
    return rows