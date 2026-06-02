from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .archive import result_to_dict as archive_to_dict
from .engine import run_investigation
from .exporting import legion_results_to_maltego_rows, write_maltego_csv
from .links import result_to_dict as link_to_dict
from .gui import main as gui_main
from .ranking import result_to_dict as ranked_to_dict
from .search import result_to_dict as web_to_dict
from .memory import OsintMemory
from .learning import build_features, train_model
from .bridge import serve_phantom_control_bridge
from .legion import PhantomLegion
from .worker import run_phantom_worker_agent, serve_phantom_worker, create_phantom_coordinator_server
import json
from .launcher import launch_phantom_app

app = typer.Typer(add_completion=False, help="Standalone OSINT research agent.")
feedback_app = typer.Typer(add_completion=False, help="Collect feedback and train the ranking model.")
console = Console()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = PROJECT_ROOT / "reports"


@app.command()
def gui() -> None:
    """Launch the local GUI."""

    gui_main()


@feedback_app.command("add")
def add_feedback(
    subject: str = typer.Argument(..., help="Subject used during the investigation."),
    url: str = typer.Argument(..., help="Source URL to label."),
    kind: str = typer.Option("web", help="Source kind, like web, archive, pdf, or link."),
    title: str = typer.Option("", help="Optional source title."),
    reason: str = typer.Option("", help="Optional source reason or excerpt."),
    score: float = typer.Option(1.0, help="Relevance label from 0 to 1, or 0 to 100."),
    trail_depth: int = typer.Option(0, help="Depth in the pointer trail when this source was found."),
    trail_score: float = typer.Option(0.0, help="Pointer-trail confidence score for this source."),
    trail_strayed: bool = typer.Option(False, help="Whether this source was found off the strongest trail."),
    memory_db: Path = typer.Option(Path(".osint_memory.sqlite3"), help="SQLite database used to remember past work."),
) -> None:
    with OsintMemory(memory_db) as memory:
        features = build_features(
            subject,
            kind=kind,
            title=title,
            url=url,
            text=reason,
            source_score=float(score) * 100.0,
            trail_depth=trail_depth,
            trail_score=trail_score,
            trail_strayed=trail_strayed,
        )
        payload = {"features": features.tolist(), "kind": kind, "title": title, "url": url, "reason": reason, "trail_depth": trail_depth, "trail_score": trail_score, "trail_strayed": trail_strayed}
        memory.add_feedback(subject, url, kind, float(score), json.dumps(payload))
    console.print(f"Saved feedback for {url}")


@feedback_app.command("train")
def train_feedback(
    memory_db: Path = typer.Option(Path(".osint_memory.sqlite3"), help="SQLite database used to remember past work."),
    epochs: int = typer.Option(250, help="Number of training epochs."),
    lr: float = typer.Option(0.001, help="Learning rate for trainer."),
    margin: float = typer.Option(0.1, help="Margin for pairwise loss."),
    pairs_strategy: str = typer.Option("all", help="Pair sampling: 'all' or 'random'."),
    pairs_per_subject: int = typer.Option(200, help="If 'random', number of pairs per subject."),
    val_split: float = typer.Option(0.2, help="Fraction of subjects for validation (0-1)."),
    device: str = typer.Option("cpu", help="Torch device to use (cpu or cuda)."),
    checkpoint: Path | None = typer.Option(None, help="Optional checkpoint output path."),
) -> None:
    with OsintMemory(memory_db) as memory:
        stats, metrics, ck = train_model(
            memory,
            epochs=epochs,
            lr=lr,
            margin=margin,
            checkpoint_path=str(checkpoint) if checkpoint else None,
            device=device,
            pairs_strategy=pairs_strategy,
            pairs_per_subject=int(pairs_per_subject) if pairs_per_subject else None,
            val_split=float(val_split),
        )
    console.print(f"Trained on {stats.examples} pair(s); loss={stats.loss:.4f}; NDCG@10={metrics.ndcg_at_10:.4f}; MRR={metrics.mrr:.4f}; checkpoint={ck}")


@app.command("app")
def app_launcher(
    host: str = typer.Option("127.0.0.1", help="Host interface for the coordinator."),
    port: int = typer.Option(8780, help="TCP port for the coordinator."),
    token: str = typer.Option("phantom", help="Authentication token required by workers and clients."),
    db_path: Path | None = typer.Option(Path(".phantom_coordinator.sqlite3"), help="SQLite database path for the coordinator."),
    worker_count: int = typer.Option(1, help="Number of local workers to start."),
    bridge_host: str = typer.Option("0.0.0.0", help="Host interface for the control bridge."),
    bridge_port: int = typer.Option(8790, help="TCP port for the control bridge."),
) -> None:
    """Launch the coordinator, workers, and GUI together."""

    console.print(f"Starting PHANTOM_LEGION app on {host}:{port} with {max(1, worker_count)} worker(s)")
    launch_phantom_app(host=host, port=port, token=token, db_path=db_path, worker_count=worker_count, bridge_host=bridge_host, bridge_port=bridge_port, open_gui=True)


@app.command()
def investigate(
    subject: str = typer.Argument(..., help="Target subject to investigate."),
    pdf: list[Path] = typer.Option([], "--pdf", help="Local PDF file(s) to extract."),
    web_limit: int = typer.Option(10, help="Maximum web search results to collect."),
    archive_limit: int = typer.Option(10, help="Maximum Internet Archive results to collect."),
    follow_links: bool = typer.Option(True, "--follow-links/--no-follow-links", help="Fetch result pages and inspect outbound links."),
    track_target: bool = typer.Option(True, "--track-target/--no-track-target", help="Prioritize pointer trails and keep following likely target links."),
    crawl_depth: int = typer.Option(1, help="Maximum recursive crawl depth."),
    max_pages: int = typer.Option(30, help="Maximum number of pages to visit recursively."),
    link_limit: int = typer.Option(20, help="Maximum outbound links to keep per page."),
    allow_domain: list[str] = typer.Option([], "--allow-domain", help="Only follow and crawl these domains."),
    deny_domain: list[str] = typer.Option([], "--deny-domain", help="Never follow or crawl these domains."),
    open_crawl: bool = typer.Option(False, "--open-crawl", help="Disable the default allowlist and crawl outward more freely."),
    memory_db: Path = typer.Option(Path(".osint_memory.sqlite3"), help="SQLite database used to remember past work."),
    json_output: Path | None = typer.Option(None, help="Optional JSON export path."),
    csv_output: Path | None = typer.Option(None, help="Optional CSV export path."),
    output: Path | None = typer.Option(None, help="Optional path to write the markdown report."),
) -> None:
    """Collect evidence from the web, Internet Archive, links, PDFs, and memory."""

    result = run_investigation(
        subject,
        pdf_sources=[str(path) for path in pdf],
        web_limit=web_limit,
        archive_limit=archive_limit,
        follow_links=follow_links,
        track_trails=track_target,
        crawl_depth=crawl_depth,
        max_pages=max_pages,
        link_limit=link_limit,
        allow_domains=allow_domain or None,
        deny_domains=deny_domain or None,
        open_crawl=open_crawl,
        memory_db=memory_db,
        json_output=json_output,
        csv_output=csv_output,
    )

    console.print(Panel.fit(f"Collected evidence for: {subject}", title="OSINT Agent"))
    _print_summary_table(
        "Memory",
        [
            {
                "source": "queries",
                "pages": str(result.memory_stats.get("queries", 0)),
                "preview": "cached search queries",
            },
            {
                "source": "pages",
                "pages": str(result.memory_stats.get("pages", 0)),
                "preview": "cached page fetches",
            },
            {
                "source": "links",
                "pages": str(result.memory_stats.get("links", 0)),
                "preview": "cached discovered links",
            },
            {
                "source": "pdfs",
                "pages": str(result.memory_stats.get("pdfs", 0)),
                "preview": "cached PDF extractions",
            },
            {
                "source": "visits",
                "pages": str(result.memory_stats.get("visits", 0)),
                "preview": "remembered crawl visits",
            },
            {
                "source": "cache hits",
                "pages": str(result.memory_stats.get("cache_hits", 0)),
                "preview": "served from memory during crawl",
            },
        ],
    )
    _print_summary_table(
        "Crawl Tree",
        [
            {
                "source": url,
                "pages": str(index + 1),
                "preview": "visited page",
            }
            for index, url in enumerate(result.crawl_result.visited_urls)
        ],
    )
    _print_summary_table("Ranked Sources", [ranked_to_dict(result_item) for result_item in result.ranked_sources])
    _print_summary_table("Web Sources", [web_to_dict(result_item) for result_item in result.web_results])
    _print_summary_table("Internet Archive", [archive_to_dict(result_item) for result_item in result.archive_results])
    _print_summary_table("Discovered Links", [link_to_dict(result_item) for result_item in result.crawl_result.discovered_links])
    _print_summary_table(
        "PDFs",
        [
            {
                "source": document.source,
                "pages": str(document.page_count),
                "preview": document.text[:200].replace("\n", " "),
            }
            for document in result.pdf_documents
        ],
    )

    if output is not None:
        output.write_text(result.report, encoding="utf-8")
        console.print(f"\nWrote report to {output}")
    else:
        console.print("\n" + result.report)


def _print_summary_table(title: str, rows: list[dict[str, str]]) -> None:
    table = Table(title=title, show_lines=False)
    if title == "Ranked Sources":
        table.add_column("Score", style="bold")
        table.add_column("Kind")
        table.add_column("Title")
        table.add_column("URL")
        table.add_column("Reason")
        for row in rows:
            table.add_row(row.get("score", ""), row.get("kind", ""), row.get("title", ""), row.get("url", ""), row.get("reason", ""))
    elif title == "Discovered Links":
        table.add_column("PDF", style="bold")
        table.add_column("Text")
        table.add_column("URL")
        table.add_column("Source Page")
        for row in rows:
            table.add_row(row.get("is_pdf", ""), row.get("text", ""), row.get("url", ""), row.get("source_page", ""))
    elif title == "Web Sources":
        table.add_column("Title", style="bold")
        table.add_column("URL")
        table.add_column("Snippet")
        for row in rows:
            table.add_row(row.get("title", ""), row.get("url", ""), row.get("snippet", ""))
    elif title == "Internet Archive":
        table.add_column("Identifier", style="bold")
        table.add_column("Title")
        table.add_column("URL")
        for row in rows:
            table.add_row(row.get("identifier", ""), row.get("title", ""), row.get("url", ""))
    elif title == "Crawl Tree":
        table.add_column("Step", style="bold")
        table.add_column("URL")
        table.add_column("Note")
        for row in rows:
            table.add_row(row.get("pages", ""), row.get("source", ""), row.get("preview", ""))
    else:
        table.add_column("Source", style="bold")
        table.add_column("Pages")
        table.add_column("Preview")
        for row in rows:
            table.add_row(row.get("source", ""), row.get("pages", ""), row.get("preview", ""))

    console.print(table)


@app.command()
def legion(
    subjects: list[str] = typer.Argument(..., help="One or more subjects to investigate."),
    num_agents: int = typer.Option(1, help="Number of agents per subject (collaborative mode)."),
    mode: str = typer.Option("parallel", help="Mode: 'parallel' or 'collaborative'."),
    track_target: bool = typer.Option(True, "--track-target/--no-track-target", help="Prioritize pointer trails and keep following likely target links."),
    memory_db: Path = typer.Option(Path(".osint_memory.sqlite3"), help="SQLite database used to remember past work."),
    targets: list[str] = typer.Option([], "--target", help="Optional remote hosts to dispatch to (ssh hostnames). Can be repeated."),
    worker_urls: list[str] = typer.Option([], "--worker-url", help="Optional PHANTOM_LEGION worker URLs. Can be repeated."),
    coordinator_url: str | None = typer.Option(None, help="Optional PHANTOM_LEGION coordinator URL for queued distributed dispatch."),
    token: str = typer.Option("phantom", help="Authentication token for workers and coordinator."),
    ssh_user: str | None = typer.Option(None, help="Optional SSH user for remote dispatch."),
    remote_cmd: str | None = typer.Option(None, help="Optional remote command template; uses {subject} placeholder."),
    top_k: int = typer.Option(20, help="Number of merged sources to include in the legion report."),
) -> None:
    """Dispatch a PHANTOM_LEGION to investigate subjects."""
    legion = PhantomLegion(max_workers=min(8, max(1, num_agents)))
    if coordinator_url:
        results = legion.dispatch_cluster(subjects, coordinator_url, token=token, top_k=top_k, memory_db=str(memory_db), track_trails=track_target)
    elif worker_urls:
        results = legion.dispatch_workers(subjects, worker_urls, num_agents=num_agents, mode=mode, top_k=top_k, memory_db=str(memory_db), track_trails=track_target)
    elif targets:
        results = legion.dispatch_remote(subjects, targets, ssh_user=ssh_user, remote_cmd=remote_cmd)
    else:
        results = legion.dispatch(subjects, num_agents=num_agents, mode=mode, top_k=top_k, memory_db=str(memory_db), track_trails=track_target)
    maltego_rows = legion_results_to_maltego_rows(results)
    maltego_label = "_".join(item.replace(" ", "_") for item in subjects[:3]) or "legion"
    maltego_output = REPORTS_DIR / "maltego" / f"phantom_{maltego_label}.csv"
    for res in results:
        console.print(f"Subject: {res.subject} — results: {len(res.results)}")
        # write merged report to file
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORTS_DIR / f"phantom_{res.subject.replace(' ', '_')}.md"
        out.write_text(res.merged_report or "", encoding="utf-8")
        console.print(f"Wrote merged report: {out}")
    write_maltego_csv(maltego_output, maltego_rows)
    console.print(f"Wrote Maltego CSV: {maltego_output}")


@app.command("phantom-worker")
def phantom_worker(
    host: str = typer.Option("127.0.0.1", help="Host interface to bind."),
    port: int = typer.Option(8765, help="TCP port to listen on."),
    coordinator_url: str | None = typer.Option(None, help="Optional coordinator URL to join as a distributed worker."),
    token: str = typer.Option("phantom", help="Authentication token for the coordinator."),
    poll_interval: float = typer.Option(2.0, help="Seconds between queue polls."),
    stop_after: int | None = typer.Option(None, help="Optional number of jobs to process before exiting."),
) -> None:
    """Run a PHANTOM_LEGION worker.

    If `--coordinator-url` is provided, this process joins the distributed queue and polls for jobs.
    Otherwise it serves the legacy direct HTTP worker endpoint.
    """
    if coordinator_url:
        console.print(f"Joining PHANTOM_LEGION coordinator at {coordinator_url} as distributed worker")
        run_phantom_worker_agent(coordinator_url, token, poll_interval=poll_interval, memory_db=".osint_memory.sqlite3", stop_after=stop_after)
        return
    console.print(f"Starting PHANTOM_LEGION HTTP worker on {host}:{port}")
    serve_phantom_worker(host=host, port=port)


@app.command("phantom-coordinator")
def phantom_coordinator(
    host: str = typer.Option("127.0.0.1", help="Host interface to bind."),
    port: int = typer.Option(8780, help="TCP port to listen on."),
    token: str = typer.Option("phantom", help="Authentication token required by workers and clients."),
    db_path: Path | None = typer.Option(None, help="Optional SQLite database path for persistent job queue."),
) -> None:
    """Run the PHANTOM_LEGION job coordinator."""
    console.print(f"Starting PHANTOM_LEGION coordinator on {host}:{port}")
    server = create_phantom_coordinator_server(host=host, port=port, token=token, db_path=str(db_path) if db_path else None)
    try:
        server.serve_forever()
    finally:
        server.server_close()


@app.command("bridge")
def bridge(
    host: str = typer.Option("127.0.0.1", help="Host interface to bind the control bridge."),
    port: int = typer.Option(8790, help="TCP port to listen on for remote commands."),
    token: str = typer.Option("phantom", help="Authentication token required by the bridge."),
    memory_db: Path = typer.Option(Path(".osint_memory.sqlite3"), help="SQLite database used to remember past work."),
    reports_dir: Path = typer.Option(REPORTS_DIR, help="Directory where bridge-triggered reports are written."),
    max_workers: int = typer.Option(2, help="Background job workers for bridge commands."),
) -> None:
    """Run an authenticated HTTP bridge for ESP32 or Arduino control."""

    console.print(f"Starting PHANTOM_LEGION control bridge on {host}:{port}")
    serve_phantom_control_bridge(host=host, port=port, token=token, memory_db=str(memory_db), reports_dir=reports_dir, max_workers=max_workers)


if __name__ == "__main__":
    app()
