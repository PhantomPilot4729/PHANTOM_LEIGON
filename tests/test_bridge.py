from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib import request as urllib_request

from osint_agent.bridge import create_phantom_control_bridge_server


def _post_json(url: str, payload: dict, token: str):
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json", "X-Phantom-Token": token}, method="POST")
    with urllib_request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _get_json(url: str, token: str | None = None):
    headers = {"X-Phantom-Token": token} if token else {}
    req = urllib_request.Request(url, headers=headers, method="GET")
    with urllib_request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _wait_for_job(base: str, job_id: str, token: str) -> dict:
    deadline = time.time() + 10.0
    while time.time() < deadline:
        job = _get_json(f"{base}/job/{job_id}", token)
        if job.get("status") in {"done", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not complete in time")


def test_bridge_investigate_command(monkeypatch, tmp_path: Path):
    class FakeResult:
        def __init__(self, subject: str):
            self.subject = subject
            self.report = f"Report for {subject}\n"
            self.ranked_sources = [object()]
            self.web_results = [object()]
            self.archive_results = []
            self.memory_stats = {"cache_hits": 0}

    monkeypatch.setattr("osint_agent.bridge.run_investigation", lambda subject, **kwargs: FakeResult(subject))

    token = "bridge-token"
    server = create_phantom_control_bridge_server(port=0, token=token, reports_dir=tmp_path / "reports")
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"

    try:
        health = _get_json(f"{base}/health")
        assert health["status"] == "ok"

        queued = _post_json(f"{base}/command", {"command": "investigate", "subject": "delta"}, token)
        assert queued["status"] == "queued"

        job = _wait_for_job(base, queued["job_id"], token)
        assert job["status"] == "done"
        assert job["result"]["subject"] == "delta"
        assert Path(job["result"]["report_path"]).exists()
    finally:
        server.state.close()  # type: ignore[attr-defined]
        server.shutdown()
        thread.join(timeout=5)


def test_bridge_legion_command(monkeypatch, tmp_path: Path):
    class FakeLegionResult:
        def __init__(self, subject: str):
            self.subject = subject
            self.results = [{"subject": subject}]
            self.merged_sources = [{"url": f"https://example.com/{subject}", "weight": 90.0, "freq": 1, "titles": [subject], "reasons": ["hit"], "kinds": ["web"], "sources": ["web"]}]
            self.merged_report = f"# {subject}\n"

    class FakeLegion:
        def __init__(self, max_workers: int):
            self.max_workers = max_workers

        def dispatch(self, subjects, num_agents, mode, top_k, memory_db, track_trails=True):
            return [FakeLegionResult(subject) for subject in subjects]

    monkeypatch.setattr("osint_agent.bridge.PhantomLegion", FakeLegion)

    token = "bridge-token"
    server = create_phantom_control_bridge_server(port=0, token=token, reports_dir=tmp_path / "reports")
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"

    try:
        queued = _post_json(f"{base}/command", {"command": "legion", "subjects": ["alpha", "beta"], "mode": "parallel", "num_agents": 2}, token)
        assert queued["status"] == "queued"

        job = _wait_for_job(base, queued["job_id"], token)
        assert job["status"] == "done"
        assert job["result"]["command"] == "legion"
        assert len(job["result"]["subjects"]) == 2
        assert Path(job["result"]["subjects"][0]["report_path"]).exists()
    finally:
        server.state.close()  # type: ignore[attr-defined]
        server.shutdown()
        thread.join(timeout=5)