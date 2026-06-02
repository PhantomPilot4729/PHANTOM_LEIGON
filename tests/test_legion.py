from pathlib import Path

from types import SimpleNamespace
import subprocess

from osint_agent.legion import PhantomLegion


def fake_run(subject, **kwargs):
    class Item:
        def __init__(self, url, score, title="t", reason="r", source="s", kind="web", heuristic_score=None, learned_score=None):
            self.url = url
            self.score = score
            self.title = title
            self.reason = reason
            self.source = source
            self.kind = kind
            self.heuristic_score = heuristic_score if heuristic_score is not None else score - 5
            self.learned_score = learned_score if learned_score is not None else score + 5

    class R:
        def __init__(self, subject):
            self.subject = subject
            # two ranked sources with different scores
            self.ranked_sources = [
                Item(f"https://example.com/{subject}/1", 80.0, title="A", kind="web", heuristic_score=78.0, learned_score=82.0),
                Item(f"https://example.com/{subject}/2", 60.0, title="B", kind="pdf", heuristic_score=55.0, learned_score=63.0),
            ]
            self.report = f"Report for {subject}"

    return R(subject)


def test_legion_parallel(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("osint_agent.legion.run_investigation", fake_run)
    legion = PhantomLegion(max_workers=2)
    results = legion.dispatch(["alpha", "beta"], num_agents=1, mode="parallel", memory_db=str(tmp_path / "mem.db"))
    assert len(results) == 2
    assert all(isinstance(r.merged_report, str) for r in results)


def test_legion_collaborative(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("osint_agent.legion.run_investigation", fake_run)
    legion = PhantomLegion(max_workers=2)
    results = legion.dispatch(["gamma"], num_agents=3, mode="collaborative", memory_db=str(tmp_path / "mem.db"))
    assert len(results) == 1
    merged = results[0].merged_report
    assert merged
    assert "https://example.com/gamma/1" in merged or "Report for gamma" in merged
    assert results[0].merged_sources
    assert results[0].merged_sources[0]["url"].startswith("https://example.com/gamma/")
    assert results[0].merged_sources[0]["avg_heuristic"] >= results[0].merged_sources[0]["avg_learned"] - 10


def test_legion_path_metrics(monkeypatch, tmp_path: Path):
    def fake_run_with_trail(subject, **kwargs):
        class Item:
            def __init__(self, url, score, trail_score, trail_strayed=False):
                self.url = url
                self.score = score
                self.title = "Trail"
                self.reason = "trail path"
                self.source = "link"
                self.kind = "link"
                self.heuristic_score = score
                self.learned_score = score
                self.trail_score = trail_score
                self.trail_strayed = trail_strayed
                self.trail_depth = 2
                self.path_confidence = min(100.0, trail_score * 5.0)
                self.drift_score = max(0.0, 100.0 - self.path_confidence + (15.0 if trail_strayed else 0.0))

        class R:
            def __init__(self, subject):
                self.subject = subject
                self.ranked_sources = [
                    Item(f"https://example.com/{subject}/pointer", 70.0, 12.0),
                    Item(f"https://example.com/{subject}/detour", 45.0, 2.0, trail_strayed=True),
                ]
                self.report = f"Report for {subject}"

        return R(subject)

    monkeypatch.setattr("osint_agent.legion.run_investigation", fake_run_with_trail)
    legion = PhantomLegion(max_workers=2)
    results = legion.dispatch(["theta"], num_agents=1, mode="parallel", memory_db=str(tmp_path / "mem.db"))

    merged_report = results[0].merged_report
    assert "path=" in merged_report
    assert "drift=" in merged_report
    assert results[0].merged_sources[0]["avg_path_confidence"] > results[0].merged_sources[0]["avg_drift_score"]


def test_legion_remote_dispatch(monkeypatch):
    calls = []

    def fake_run_cmd(cmd, capture_output, text, timeout, check):
        calls.append(cmd)
        return SimpleNamespace(stdout="https://example.com/remote/1\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run_cmd)
    legion = PhantomLegion(max_workers=2)
    results = legion.dispatch_remote(["delta"], ["host1", "host2"], ssh_user="user", remote_cmd="python -m osint_agent.cli investigate {subject}")
    assert len(results) == 1
    assert len(calls) == 2
    assert "https://example.com/remote/1" in results[0].merged_report
