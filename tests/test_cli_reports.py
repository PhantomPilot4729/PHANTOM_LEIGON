from __future__ import annotations

from pathlib import Path

from osint_agent import cli
from osint_agent.exporting import legion_results_to_maltego_rows, write_maltego_csv


def test_legion_writes_report_to_reports_dir(monkeypatch, tmp_path: Path):
    class FakeResult:
        def __init__(self):
            self.subject = "test subject"
            self.results = [{"url": "https://example.com"}]
            self.merged_report = "# Report\nhello world\n"

    class FakeLegion:
        def __init__(self, max_workers: int):
            self.max_workers = max_workers

        def dispatch(self, subjects, num_agents, mode, top_k, memory_db, track_trails=True):
            assert subjects == ["test subject"]
            return [FakeResult()]

    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(cli, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(cli, "PhantomLegion", FakeLegion)

    cli.legion(
        ["test subject"],
        num_agents=1,
        mode="parallel",
        memory_db=tmp_path / "memory.sqlite3",
        targets=[],
        worker_urls=[],
        coordinator_url=None,
        token="phantom",
        ssh_user=None,
        remote_cmd=None,
        top_k=20,
    )

    output = reports_dir / "phantom_test_subject.md"
    assert output.exists()
    assert output.read_text(encoding="utf-8") == "# Report\nhello world\n"


def test_legion_maltego_export(tmp_path: Path):
    class FakeResult:
        subject = "test subject"
        merged_sources = [
            {
                "url": "https://example.com/alpha",
                "weight": 91.5,
                "freq": 3,
                "titles": ["Alpha"],
                "reasons": ["Important"],
                "kinds": ["web"],
                "sources": ["web"],
            }
        ]

    rows = legion_results_to_maltego_rows([FakeResult()])
    output = tmp_path / "maltego" / "phantom_test_subject.csv"
    write_maltego_csv(output, rows)

    content = output.read_text(encoding="utf-8")
    assert "Entity Type" in content
    assert "Website" in content
    assert "https://example.com/alpha" in content