from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from collections import deque
from typing import Any
from uuid import uuid4
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin

from .engine import run_investigation


class PersistentCoordinatorDB:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or ".phantom_coordinator.sqlite3"
        self.conn: sqlite3.Connection | None = None
        self._init_schema()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                worker_id TEXT,
                result TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                claimed_at REAL,
                completed_at REAL
            )"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS workers (
                worker_id TEXT PRIMARY KEY,
                metadata TEXT NOT NULL,
                registered_at REAL NOT NULL,
                last_seen REAL NOT NULL
            )"""
        )
        cursor.execute("""CREATE TABLE IF NOT EXISTS queue (job_id TEXT PRIMARY KEY, FOREIGN KEY(job_id) REFERENCES jobs(job_id))""")
        conn.commit()
        conn.close()

    def get_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def add_job(self, job_id: str, subject: str, payload: dict[str, Any]) -> None:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO jobs (job_id, subject, payload, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
            (job_id, subject, json.dumps(payload), time.time()),
        )
        cursor.execute("INSERT INTO queue (job_id) VALUES (?)", (job_id,))
        conn.commit()

    def claim_job(self, worker_id: str) -> dict[str, Any] | None:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT job_id FROM queue LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        job_id = row[0]
        cursor.execute("UPDATE jobs SET status = 'claimed', worker_id = ?, claimed_at = ? WHERE job_id = ?", (worker_id, time.time(), job_id))
        cursor.execute("DELETE FROM queue WHERE job_id = ?", (job_id,))
        conn.commit()
        return self._load_job(job_id)

    def complete_job(self, job_id: str, worker_id: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        conn = self.get_conn()
        cursor = conn.cursor()
        status = "failed" if error else "done"
        cursor.execute(
            "UPDATE jobs SET status = ?, worker_id = ?, result = ?, error = ?, completed_at = ? WHERE job_id = ?",
            (status, worker_id, json.dumps(result) if result else None, error, time.time(), job_id),
        )
        conn.commit()

    def _load_job(self, job_id: str) -> dict[str, Any] | None:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT job_id, subject, payload, status, worker_id, result, error FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "job_id": row[0],
            "subject": row[1],
            "payload": json.loads(row[2]),
            "status": row[3],
            "worker_id": row[4],
            "result": json.loads(row[5]) if row[5] else None,
            "error": row[6],
        }

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        return self._load_job(job_id)

    def register_worker(self, worker_id: str, metadata: dict[str, Any]) -> None:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO workers (worker_id, metadata, registered_at, last_seen) VALUES (?, ?, ?, ?)", (worker_id, json.dumps(metadata), time.time(), time.time()))
        conn.commit()

    def heartbeat_worker(self, worker_id: str) -> None:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE workers SET last_seen = ? WHERE worker_id = ?", (time.time(), worker_id))
        conn.commit()

    def cleanup_dead_workers(self, timeout_seconds: int = 300) -> None:
        conn = self.get_conn()
        cursor = conn.cursor()
        threshold = time.time() - timeout_seconds
        cursor.execute("DELETE FROM workers WHERE last_seen < ?", (threshold,))
        conn.commit()

    def recover_unclaimed_jobs(self) -> list[str]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT job_id FROM jobs WHERE status = 'claimed' AND claimed_at < ?", (time.time() - 600,))
        rows = cursor.fetchall()
        job_ids = [row[0] for row in rows]
        for job_id in job_ids:
            cursor.execute("UPDATE jobs SET status = 'queued', worker_id = NULL, claimed_at = NULL WHERE job_id = ?", (job_id,))
            cursor.execute("INSERT INTO queue (job_id) VALUES (?)", (job_id,))
        conn.commit()
        return job_ids


@dataclass(slots=True)
class PhantomJob:
    job_id: str
    subject: str
    payload: dict[str, Any]
    status: str = "queued"
    worker_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class PhantomCoordinatorState:
    token: str
    db: PersistentCoordinatorDB | None = None
    jobs: dict[str, PhantomJob] = field(default_factory=dict)
    queue: deque[str] = field(default_factory=deque)
    workers: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


class PhantomWorkerHandler(BaseHTTPRequestHandler):
    server_version = "PHANTOM_LEGION/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/health":
            self._send_json({"status": "ok"})
            return
        self.send_error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/dispatch":
            self.send_error(404, "not found")
            return
        try:
            payload = self._read_json()
            subject = str(payload.get("subject", "")).strip()
            if not subject:
                self._send_json({"error": "subject is required"}, status=400)
                return
            result = run_investigation(
                subject,
                pdf_sources=[str(path) for path in payload.get("pdf_sources", [])],
                web_limit=int(payload.get("web_limit", 10)),
                archive_limit=int(payload.get("archive_limit", 10)),
                follow_links=bool(payload.get("follow_links", True)),
                track_trails=bool(payload.get("track_trails", True)),
                crawl_depth=int(payload.get("crawl_depth", 1)),
                max_pages=int(payload.get("max_pages", 30)),
                link_limit=int(payload.get("link_limit", 20)),
                allow_domains=payload.get("allow_domains") or None,
                deny_domains=payload.get("deny_domains") or None,
                open_crawl=bool(payload.get("open_crawl", False)),
                memory_db=payload.get("memory_db") or ".osint_memory.sqlite3",
                json_output=None,
                csv_output=None,
            )
            body = {
                "subject": subject,
                "report": result.report,
                "memory_stats": result.memory_stats,
                "learning_stats": result.learning_stats,
                "ranked_sources": [asdict(item) for item in result.ranked_sources],
                "crawl_result": {
                    "visited_urls": result.crawl_result.visited_urls,
                    "discovered_links": [asdict(item) for item in result.crawl_result.discovered_links],
                    "pdf_documents": [asdict(item) for item in result.crawl_result.pdf_documents],
                    "memory_hits": result.crawl_result.memory_hits,
                    "skipped_domains": result.crawl_result.skipped_domains,
                },
            }
            self._send_json(body)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class PhantomCoordinatorHandler(BaseHTTPRequestHandler):
    server_version = "PHANTOM_COORDINATOR/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/health":
            state = self.server.state  # type: ignore[attr-defined]
            with state.lock:
                payload = {
                    "status": "ok",
                    "queue_size": len(state.queue),
                    "jobs": len(state.jobs),
                    "workers": len(state.workers),
                }
            self._send_json(payload)
            return
        if self.path.startswith("/job/"):
            job_id = self.path.split("/job/", 1)[1].strip().strip("/")
            state = self.server.state  # type: ignore[attr-defined]
            if not self._require_token(state):
                return
            with state.lock:
                if state.db:
                    job_dict = state.db.get_job_status(job_id)
                    if job_dict is None:
                        self._send_json({"error": "job not found"}, status=404)
                        return
                    self._send_json(job_dict)
                else:
                    job = state.jobs.get(job_id)
                    if job is None:
                        self._send_json({"error": "job not found"}, status=404)
                        return
                    self._send_json(_job_to_dict(job))
            return
        self.send_error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        state = self.server.state  # type: ignore[attr-defined]
        if self.path.rstrip("/") == "/register":
            if not self._require_token(state):
                return
            payload = self._read_json()
            worker_id = str(payload.get("worker_id") or uuid4().hex)
            metadata = payload.get("metadata", {})
            with state.lock:
                if state.db:
                    state.db.register_worker(worker_id, metadata)
                else:
                    state.workers[worker_id] = {"worker_id": worker_id, "metadata": metadata, "last_seen": time.time()}
            self._send_json({"worker_id": worker_id})
            return
        if self.path.rstrip("/") == "/enqueue":
            if not self._require_token(state):
                return
            payload = self._read_json()
            subject = str(payload.get("subject", "")).strip()
            if not subject:
                self._send_json({"error": "subject is required"}, status=400)
                return
            job_id = uuid4().hex
            with state.lock:
                if state.db:
                    state.db.add_job(job_id, subject, payload)
                else:
                    job = PhantomJob(job_id=job_id, subject=subject, payload=payload)
                    state.jobs[job_id] = job
                    state.queue.append(job_id)
            self._send_json({"job_id": job_id, "status": "queued"})
            return
        if self.path.rstrip("/") == "/claim":
            if not self._require_token(state):
                return
            payload = self._read_json()
            worker_id = str(payload.get("worker_id", "")).strip()
            if not worker_id:
                self._send_json({"error": "worker_id is required"}, status=400)
                return
            with state.lock:
                if state.db:
                    job_dict = state.db.claim_job(worker_id)
                    state.db.heartbeat_worker(worker_id)
                    self._send_json({"job": job_dict})
                else:
                    if worker_id not in state.workers:
                        self._send_json({"error": "worker is not registered"}, status=403)
                        return
                    job_id = state.queue.popleft() if state.queue else None
                    if not job_id:
                        self._send_json({"job": None})
                        return
                    job = state.jobs[job_id]
                    job.status = "claimed"
                    job.worker_id = worker_id
                    state.workers[worker_id]["last_seen"] = time.time()
                    self._send_json({"job": _job_to_dict(job)})
            return
        if self.path.rstrip("/") == "/complete":
            if not self._require_token(state):
                return
            payload = self._read_json()
            worker_id = str(payload.get("worker_id", "")).strip()
            job_id = str(payload.get("job_id", "")).strip()
            if not worker_id or not job_id:
                self._send_json({"error": "worker_id and job_id are required"}, status=400)
                return
            with state.lock:
                if state.db:
                    state.db.complete_job(job_id, worker_id, result=payload.get("result"), error=payload.get("error"))
                    state.db.heartbeat_worker(worker_id)
                    status = "failed" if payload.get("error") else "done"
                else:
                    job = state.jobs.get(job_id)
                    if job is None:
                        self._send_json({"error": "job not found"}, status=404)
                        return
                    job.worker_id = worker_id
                    status = "done" if not payload.get("error") else "failed"
                    job.status = status
                    job.result = payload.get("result")
                    job.error = payload.get("error")
                    state.workers.setdefault(worker_id, {"worker_id": worker_id, "metadata": {}, "last_seen": time.time()})["last_seen"] = time.time()
            self._send_json({"status": status})
            return
        self.send_error(404, "not found")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _require_token(self, state: PhantomCoordinatorState) -> bool:
        token = self.headers.get("X-Phantom-Token", "")
        if token != state.token:
            self._send_json({"error": "unauthorized"}, status=401)
            return False
        return True

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve_phantom_worker(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), PhantomWorkerHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def serve_phantom_coordinator(host: str = "127.0.0.1", port: int = 8780, token: str = "phantom") -> None:
    server = create_phantom_coordinator_server(host=host, port=port, token=token)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def create_phantom_coordinator_server(host: str = "127.0.0.1", port: int = 8780, token: str = "phantom", db_path: str | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), PhantomCoordinatorHandler)
    db = PersistentCoordinatorDB(db_path) if db_path else None
    state = PhantomCoordinatorState(token=token, db=db)
    if db:
        recovered = db.recover_unclaimed_jobs()
        if recovered:
            pass
    server.state = state  # type: ignore[attr-defined]
    return server


def run_phantom_worker_agent(
    coordinator_url: str,
    token: str,
    *,
    poll_interval: float = 2.0,
    worker_id: str | None = None,
    memory_db: str = ".osint_memory.sqlite3",
    stop_after: int | None = None,
) -> None:
    worker_id = worker_id or uuid4().hex
    register_payload = {"worker_id": worker_id, "metadata": {"memory_db": memory_db}}
    _request_json(urljoin(coordinator_url.rstrip("/") + "/", "register"), register_payload, token=token)
    processed = 0
    while True:
        claim = _request_json(urljoin(coordinator_url.rstrip("/") + "/", "claim"), {"worker_id": worker_id}, token=token)
        job = claim.get("job")
        if not job:
            if stop_after is not None and processed >= stop_after:
                return
            time.sleep(poll_interval)
            continue
        job_id = str(job.get("job_id", ""))
        payload = dict(job.get("payload", {}))
        subject = str(payload.get("subject", "")).strip()
        try:
            result = run_investigation(
                subject,
                pdf_sources=[str(path) for path in payload.get("pdf_sources", [])],
                web_limit=int(payload.get("web_limit", 10)),
                archive_limit=int(payload.get("archive_limit", 10)),
                follow_links=bool(payload.get("follow_links", True)),
                crawl_depth=int(payload.get("crawl_depth", 1)),
                max_pages=int(payload.get("max_pages", 30)),
                link_limit=int(payload.get("link_limit", 20)),
                allow_domains=payload.get("allow_domains") or None,
                deny_domains=payload.get("deny_domains") or None,
                open_crawl=bool(payload.get("open_crawl", False)),
                memory_db=payload.get("memory_db") or memory_db,
                json_output=None,
                csv_output=None,
            )
            body = {
                "subject": subject,
                "report": result.report,
                "memory_stats": result.memory_stats,
                "learning_stats": result.learning_stats,
                "ranked_sources": [asdict(item) for item in result.ranked_sources],
                "crawl_result": {
                    "visited_urls": result.crawl_result.visited_urls,
                    "discovered_links": [asdict(item) for item in result.crawl_result.discovered_links],
                    "pdf_documents": [asdict(item) for item in result.crawl_result.pdf_documents],
                    "memory_hits": result.crawl_result.memory_hits,
                    "skipped_domains": result.crawl_result.skipped_domains,
                },
            }
            _request_json(urljoin(coordinator_url.rstrip("/") + "/", "complete"), {"worker_id": worker_id, "job_id": job_id, "result": body}, token=token)
        except Exception as exc:
            _request_json(urljoin(coordinator_url.rstrip("/") + "/", "complete"), {"worker_id": worker_id, "job_id": job_id, "error": str(exc)}, token=token)
        processed += 1
        if stop_after is not None and processed >= stop_after:
            return


def _request_json(url: str, payload: dict[str, Any], *, token: str, timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json", "X-Phantom-Token": token}, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"request to {url} failed: {exc}") from exc


def _job_to_dict(job: PhantomJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "subject": job.subject,
        "payload": job.payload,
        "status": job.status,
        "worker_id": job.worker_id,
        "result": job.result,
        "error": job.error,
    }
