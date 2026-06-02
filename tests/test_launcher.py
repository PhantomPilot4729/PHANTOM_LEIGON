from __future__ import annotations

import os
from pathlib import Path

from osint_agent import launcher


def test_launch_phantom_app_starts_components(monkeypatch):
    events: list[object] = []

    def make_fake_server(label: str):
        class FakeServer:
            def serve_forever(self) -> None:
                events.append((label, "serve_forever"))

            def shutdown(self) -> None:
                events.append((label, "shutdown"))

            def server_close(self) -> None:
                events.append((label, "server_close"))

        return FakeServer()

    def fake_create_phantom_coordinator_server(**kwargs):
        events.append(("coordinator", kwargs))
        return make_fake_server("coordinator")

    def fake_create_phantom_control_bridge_server(**kwargs):
        events.append(("bridge", kwargs))
        return make_fake_server("bridge")

    def fake_wait_for_health(url: str, timeout_seconds: float = 10.0) -> None:
        events.append(("health", url, timeout_seconds))

    def fake_run_phantom_worker_agent(coordinator_url: str, token: str, **kwargs) -> None:
        events.append(("worker", coordinator_url, token, kwargs))

    def fake_gui_main() -> None:
        events.append("gui")

    monkeypatch.setattr(launcher, "create_phantom_coordinator_server", fake_create_phantom_coordinator_server)
    monkeypatch.setattr(launcher, "create_phantom_control_bridge_server", fake_create_phantom_control_bridge_server)
    monkeypatch.setattr(launcher, "_wait_for_health", fake_wait_for_health)
    monkeypatch.setattr(launcher, "run_phantom_worker_agent", fake_run_phantom_worker_agent)
    monkeypatch.setattr(launcher, "gui_main", fake_gui_main)

    launcher.launch_phantom_app(
        host="127.0.0.1",
        port=8780,
        token="phantom",
        db_path=Path(".phantom_coordinator.sqlite3"),
        worker_count=2,
        poll_interval=0.25,
        memory_db=".osint_memory.sqlite3",
        bridge_host="127.0.0.1",
        bridge_port=8791,
        open_gui=True,
    )

    assert os.environ["OSINT_AGENT_COORDINATOR_URL"] == "http://127.0.0.1:8780"
    assert os.environ["OSINT_AGENT_COORDINATOR_TOKEN"] == "phantom"
    assert os.environ["OSINT_AGENT_BRIDGE_URL"] == "http://127.0.0.1:8791"
    assert os.environ["OSINT_AGENT_BRIDGE_TOKEN"] == "phantom"
    assert any(item[0] == "coordinator" for item in events if isinstance(item, tuple))
    assert any(item[0] == "bridge" for item in events if isinstance(item, tuple))
    assert events.count("gui") == 1
    assert events.count(("coordinator", "shutdown")) == 1
    assert events.count(("bridge", "shutdown")) == 1
    assert events.count(("coordinator", "server_close")) == 1
    assert events.count(("bridge", "server_close")) == 1
    worker_events = [item for item in events if isinstance(item, tuple) and item and item[0] == "worker"]
    assert len(worker_events) == 2