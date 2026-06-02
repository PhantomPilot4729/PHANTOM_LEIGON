from __future__ import annotations

import json
import threading
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


def test_coordinator_worker_queue(monkeypatch, tmp_path: Path):
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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"

    try:
        job = _post_json(f"{base}/enqueue", {"subject": "delta", "memory_db": str(tmp_path / "memory.sqlite3")}, token)
        job_id = job["job_id"]

        worker_thread = threading.Thread(target=run_phantom_worker_agent, args=(base, token), kwargs={"poll_interval": 0.05, "memory_db": str(tmp_path / "memory.sqlite3"), "stop_after": 1}, daemon=True)
        worker_thread.start()
        worker_thread.join(timeout=10)

        assert not worker_thread.is_alive()
        status = _get_json(f"{base}/job/{job_id}", token)
        assert status["status"] == "done"
        assert status["result"]["report"] == "Report for delta"
    finally:
        server.shutdown()
        thread.join(timeout=5)
