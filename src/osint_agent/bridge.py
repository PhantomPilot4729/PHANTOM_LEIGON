from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import run_investigation
from .legion import PhantomLegion
from .schema import normalize_payload

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"
SUPPORTED_COMMANDS = {
    "status": "Return bridge status and recent job history.",
    "investigate": "Run a single subject investigation.",
    "legion": "Run a PHANTOM_LEGION dispatch across one or more subjects.",
}


@dataclass(slots=True)
class BridgeState:
    token: str
    memory_db: str
    reports_dir: Path = DEFAULT_REPORTS_DIR
    max_workers: int = 2
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    presets: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        "quick": {"command": "investigate", "web_limit": 5, "archive_limit": 5, "track_trails": True},
        "scan": {"command": "legion", "num_agents": 1, "mode": "parallel", "top_k": 10},
    })
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    executor: ThreadPoolExecutor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.reports_dir = Path(self.reports_dir)
        self.executor = ThreadPoolExecutor(max_workers=max(1, self.max_workers), thread_name_prefix="phantom-bridge")

    def submit(self, payload: dict[str, Any]) -> str:
        # normalize payload into canonical shape
        payload = normalize_payload(payload)
        command = str(payload.get("command", "")).strip().lower()
        if command not in SUPPORTED_COMMANDS:
            raise ValueError(f"unsupported command: {command or '<missing>'}")

        job_id = uuid4().hex
        timestamp = time.time()
        self._set_job(
            job_id,
            {
                "job_id": job_id,
                "command": command,
                "status": "queued",
                "submitted_at": timestamp,
                "updated_at": timestamp,
                "payload": payload,
            },
        )
        self.executor.submit(self._run_job, job_id, payload)
        return job_id

    def _run_job(self, job_id: str, payload: dict[str, Any]) -> None:
        self._update_job(job_id, status="running", updated_at=time.time())
        try:
            result = self._execute(payload)
            self._update_job(job_id, status="done", updated_at=time.time(), completed_at=time.time(), result=result, error="")
        except Exception as exc:  # pragma: no cover - exercised through job status assertions
            self._update_job(job_id, status="failed", updated_at=time.time(), completed_at=time.time(), error=str(exc), result=None)

    def _execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command", "")).strip().lower()
        if command == "status":
            return self.status_snapshot()
        if command == "investigate":
            return self._run_investigation(payload)
        if command == "legion":
            return self._run_legion(payload)
        raise ValueError(f"unsupported command: {command}")

    def _run_investigation(self, payload: dict[str, Any]) -> dict[str, Any]:
        subject = _extract_subject(payload)
        if not subject:
            raise ValueError("investigate command requires a subject")

        result = run_investigation(
            subject,
            pdf_sources=[str(path) for path in payload.get("pdf_sources", []) if path],
            web_limit=int(payload.get("web_limit", 10)),
            archive_limit=int(payload.get("archive_limit", 10)),
            follow_links=bool(payload.get("follow_links", True)),
            track_trails=bool(payload.get("track_target", payload.get("track_trails", True))),
            crawl_depth=int(payload.get("crawl_depth", 1)),
            max_pages=int(payload.get("max_pages", 30)),
            link_limit=int(payload.get("link_limit", 20)),
            allow_domains=_normalize_text_list(payload.get("allow_domains")),
            deny_domains=_normalize_text_list(payload.get("deny_domains")),
            open_crawl=bool(payload.get("open_crawl", False)),
            memory_db=payload.get("memory_db", self.memory_db),
            json_output=payload.get("json_output"),
            csv_output=payload.get("csv_output"),
        )
        report_path = self._write_report("investigate", subject, result.report)
        return {
            "command": "investigate",
            "subject": subject,
            "report_path": str(report_path),
            "report_excerpt": result.report[:500],
            "ranked_sources": len(result.ranked_sources),
            "web_results": len(result.web_results),
            "archive_results": len(result.archive_results),
            "memory_hits": result.memory_stats.get("cache_hits", 0),
        }

    def _run_legion(self, payload: dict[str, Any]) -> dict[str, Any]:
        subjects = _normalize_text_list(payload.get("subjects"))
        if not subjects:
            subject = _extract_subject(payload)
            if subject:
                subjects = [subject]
        if not subjects:
            raise ValueError("legion command requires at least one subject")

        num_agents = int(payload.get("num_agents", 1))
        mode = str(payload.get("mode", "parallel")).strip().lower()
        top_k = int(payload.get("top_k", 20))
        legion = PhantomLegion(max_workers=min(8, max(1, num_agents)))

        if payload.get("coordinator_url"):
            results = legion.dispatch_cluster(subjects, str(payload["coordinator_url"]), token=str(payload.get("token", self.token)), top_k=top_k, memory_db=str(payload.get("memory_db", self.memory_db)), track_trails=bool(payload.get("track_target", payload.get("track_trails", True))))
        elif payload.get("worker_urls"):
            results = legion.dispatch_workers(subjects, _normalize_text_list(payload.get("worker_urls")), num_agents=num_agents, mode=mode, top_k=top_k, memory_db=str(payload.get("memory_db", self.memory_db)), track_trails=bool(payload.get("track_target", payload.get("track_trails", True))))
        elif payload.get("targets"):
            results = legion.dispatch_remote(subjects, _normalize_text_list(payload.get("targets")), ssh_user=payload.get("ssh_user"), remote_cmd=payload.get("remote_cmd"))
        else:
            results = legion.dispatch(subjects, num_agents=num_agents, mode=mode, top_k=top_k, memory_db=str(payload.get("memory_db", self.memory_db)), track_trails=bool(payload.get("track_target", payload.get("track_trails", True))))

        subject_reports: list[dict[str, Any]] = []
        for result in results:
            report_path = self._write_report("legion", result.subject, result.merged_report or "")
            subject_reports.append(
                {
                    "subject": result.subject,
                    "report_path": str(report_path),
                    "result_count": len(result.results),
                    "merged_sources": len(result.merged_sources),
                    "report_excerpt": (result.merged_report or "")[:500],
                }
            )
        return {
            "command": "legion",
            "subjects": subject_reports,
            "result_count": len(results),
            "mode": mode,
            "num_agents": num_agents,
        }

    def _write_report(self, prefix: str, subject: str, content: str) -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        safe_subject = _slugify(subject)
        output = self.reports_dir / "bridge" / f"{prefix}_{safe_subject}.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content or "", encoding="utf-8")
        return output

    def _set_job(self, job_id: str, payload: dict[str, Any]) -> None:
        with self.lock:
            self.jobs[job_id] = payload

    def _update_job(self, job_id: str, **updates: Any) -> None:
        with self.lock:
            job = self.jobs.setdefault(job_id, {"job_id": job_id})
            job.update(updates)

    def status_snapshot(self) -> dict[str, Any]:
        with self.lock:
            jobs = list(self.jobs.values())
        counts = {status: 0 for status in ("queued", "running", "done", "failed")}
        for job in jobs:
            counts[str(job.get("status", "queued"))] = counts.get(str(job.get("status", "queued")), 0) + 1
        last_job = max(jobs, key=lambda item: float(item.get("updated_at", 0.0)), default=None)
        return {
            "service": "phantom-control-bridge",
            "status": "ok",
            "commands": SUPPORTED_COMMANDS,
            "queued": counts["queued"],
            "running": counts["running"],
            "done": counts["done"],
            "failed": counts["failed"],
            "last_job": last_job,
        }

    def job_snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


class PhantomControlBridgeHandler(BaseHTTPRequestHandler):
    server_version = "PHANTOM_CONTROL_BRIDGE/1.0"

    def _state(self) -> BridgeState:
        return self.server.state  # type: ignore[attr-defined]

    def _authorized(self) -> bool:
        return self.headers.get("X-Phantom-Token", "") == self._state().token

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path == "/health":
            self._send_json({"status": "ok", "service": "phantom-control-bridge"})
            return
        if path == "/status":
            if not self._authorized():
                self._send_json({"error": "unauthorized"}, status=403)
                return
            self._send_json(self._state().status_snapshot())
            return
        if path == "/commands":
            if not self._authorized():
                self._send_json({"error": "unauthorized"}, status=403)
                return
            self._send_json({"commands": SUPPORTED_COMMANDS})
            return
        if path.startswith("/job/"):
            if not self._authorized():
                self._send_json({"error": "unauthorized"}, status=403)
                return
            job_id = path.split("/", 2)[2]
            job = self._state().job_snapshot(job_id)
            if job is None:
                self._send_json({"error": "job not found"}, status=404)
                return
            self._send_json(job)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path.startswith("/preset/"):
            if not self._authorized():
                self._send_json({"error": "unauthorized"}, status=403)
                return
            name = path.split("/", 2)[2]
            preset = self._state().presets.get(name)
            if preset is None:
                self._send_json({"error": "preset not found"}, status=404)
                return
            try:
                job_id = self._state().submit(dict(preset))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            return
        if path != "/command":
            self._send_json({"error": "not found"}, status=404)
            return
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, status=403)
            return
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "invalid JSON payload"}, status=400)
            return
        try:
            job_id = self._state().submit(payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"job_id": job_id, "status": "queued"}, status=202)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")


def create_phantom_control_bridge_server(
    host: str = "127.0.0.1",
    port: int = 8790,
    token: str = "phantom",
    *,
    memory_db: str = ".osint_memory.sqlite3",
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
    max_workers: int = 2,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), PhantomControlBridgeHandler)
    server.state = BridgeState(token=token, memory_db=memory_db, reports_dir=Path(reports_dir), max_workers=max_workers)  # type: ignore[attr-defined]
    return server


def serve_phantom_control_bridge(
    host: str = "127.0.0.1",
    port: int = 8790,
    token: str = "phantom",
    *,
    memory_db: str = ".osint_memory.sqlite3",
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
    max_workers: int = 2,
) -> None:
    server = create_phantom_control_bridge_server(host=host, port=port, token=token, memory_db=memory_db, reports_dir=reports_dir, max_workers=max_workers)
    try:
        server.serve_forever()
    finally:
        server.state.close()  # type: ignore[attr-defined]
        server.server_close()


def _extract_subject(payload: dict[str, Any]) -> str:
    subject = str(payload.get("subject", "")).strip()
    if subject:
        return subject
    subjects = _normalize_text_list(payload.get("subjects"))
    return subjects[0] if subjects else ""


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _slugify(value: str) -> str:
    cleaned = [char.lower() if char.isalnum() else "_" for char in value.strip()]
    slug = "".join(cleaned).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "command"
