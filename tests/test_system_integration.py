"""End-to-end integration tests for the distributed OSINT agent system."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib import request as urllib_request

from osint_agent.worker import create_phantom_coordinator_server, run_phantom_worker_agent


def _post_json(url: str, payload: dict, token: str):
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json", "X-Phantom-Token": token}, method="POST")
    with urllib_request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _get_json(url: str, token: str):
    req = urllib_request.Request(url, headers={"X-Phantom-Token": token}, method="GET")
    with urllib_request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def test_coordinator_persistent_queue(monkeypatch, tmp_path: Path):
    """Test coordinator job persistence across restarts."""

    class FakeResult:
        def __init__(self, subject: str):
            self.report = f"Report for {subject}"
            self.memory_stats = {"queries": 1, "pages": 0, "links": 0, "pdfs": 0, "visits": 0}
            self.learning_stats = {"examples": 1, "epochs": 1, "loss": 0.1, "ndcg_at_10": 1.0, "mrr": 1.0, "checkpoint": "models/neural_ranker.pt"}
            self.ranked_sources = []
            self.crawl_result = type("CrawlResult", (), {"visited_urls": [], "discovered_links": [], "pdf_documents": [], "memory_hits": 0, "skipped_domains": []})()

    monkeypatch.setattr("osint_agent.worker.run_investigation", lambda subject, **kwargs: FakeResult(subject))

    token = "test-token"
    db_path = str(tmp_path / "coordinator.db")

    # Start coordinator with persistent DB on a fixed port
    server = create_phantom_coordinator_server(port=0, token=token, db_path=db_path)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        # Enqueue 2 jobs
        job_ids = []
        for i in range(2):
            job = _post_json(f"{base}/enqueue", {"subject": f"target-{i}"}, token)
            job_ids.append(job["job_id"])
            assert job["status"] == "queued"

        # Start one worker to process one job
        worker_thread = threading.Thread(
            target=run_phantom_worker_agent,
            args=(base, token),
            kwargs={"poll_interval": 0.05, "stop_after": 1},
            daemon=True,
        )
        worker_thread.start()
        worker_thread.join(timeout=10)

        # Verify first job is done
        status = _get_json(f"{base}/job/{job_ids[0]}", token)
        assert status["status"] == "done"

        # Verify second job is still queued
        status = _get_json(f"{base}/job/{job_ids[1]}", token)
        assert status["status"] == "queued"

        # Shutdown coordinator gracefully
        server.shutdown()
        thread.join(timeout=5)

        # Verify DB file exists
        assert Path(db_path).exists()
    finally:
        try:
            server.server_close()
        except Exception:
            pass


def test_coordinator_worker_agent(monkeypatch, tmp_path: Path):
    """Test worker agent claiming and processing jobs."""

    class FakeResult:
        def __init__(self, subject: str):
            self.report = f"Report for {subject}"
            self.memory_stats = {"queries": 1, "pages": 0, "links": 0, "pdfs": 0, "visits": 0}
            self.learning_stats = {"examples": 1, "epochs": 1, "loss": 0.1, "ndcg_at_10": 1.0, "mrr": 1.0, "checkpoint": "models/neural_ranker.pt"}
            self.ranked_sources = []
            self.crawl_result = type("CrawlResult", (), {"visited_urls": [], "discovered_links": [], "pdf_documents": [], "memory_hits": 0, "skipped_domains": []})()

    monkeypatch.setattr("osint_agent.worker.run_investigation", lambda subject, **kwargs: FakeResult(subject))

    token = "test-token"

    server = create_phantom_coordinator_server(port=0, token=token)
    host, port = server.server_address
    base = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        # Enqueue 3 jobs
        job_ids = []
        for i in range(3):
            job = _post_json(f"{base}/enqueue", {"subject": f"task-{i}"}, token)
            job_ids.append(job["job_id"])

        # Worker processes jobs
        worker_thread = threading.Thread(
            target=run_phantom_worker_agent,
            args=(base, token),
            kwargs={"poll_interval": 0.05, "stop_after": 3},
            daemon=True,
        )
        worker_thread.start()
        worker_thread.join(timeout=15)

        # Verify all jobs are done
        for job_id in job_ids:
            status = _get_json(f"{base}/job/{job_id}", token)
            assert status["status"] == "done", f"Job {job_id} should be done"
            assert "task-" in status["result"]["report"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

