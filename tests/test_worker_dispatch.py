from pathlib import Path

from osint_agent.legion import PhantomLegion


def test_http_worker_dispatch(monkeypatch, tmp_path: Path):
    calls = []

    def fake_invoke(worker_url, payload, timeout=300):
        calls.append((worker_url, payload))
        return {
            "subject": payload["subject"],
            "report": f"Report from {worker_url}",
            "ranked_sources": [
                {
                    "kind": "web",
                    "score": 82,
                    "title": "A",
                    "url": f"{worker_url}/item",
                    "reason": "ok",
                    "source": "worker",
                    "heuristic_score": 78,
                    "learned_score": 84,
                }
            ],
        }

    monkeypatch.setattr("osint_agent.legion._invoke_http_worker", fake_invoke)
    legion = PhantomLegion(max_workers=2)
    results = legion.dispatch_workers(["omega"], ["http://worker-1", "http://worker-2"], mode="collaborative", num_agents=2, memory_db=str(tmp_path / "mem.db"))
    assert len(results) == 1
    assert len(calls) == 2
    assert results[0].merged_sources
    assert results[0].merged_sources[0]["url"].startswith("http://worker-")
