from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from urllib import request as urllib_request

from .bridge import create_phantom_control_bridge_server
from .gui import main as gui_main
from .worker import create_phantom_coordinator_server, run_phantom_worker_agent
from .supervisor import Supervisor


def _wait_for_health(url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    health_url = url.rstrip("/") + "/health"
    while time.time() < deadline:
        try:
            with urllib_request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"Coordinator did not become ready at {health_url}")


def launch_phantom_app(
    *,
    host: str = "127.0.0.1",
    port: int = 8780,
    token: str = "phantom",
    db_path: Path | None = None,
    worker_count: int = 1,
    poll_interval: float = 2.0,
    memory_db: str = ".osint_memory.sqlite3",
    bridge_host: str = "0.0.0.0",
    bridge_port: int = 8790,
    open_gui: bool = True,
) -> None:
    coordinator_db = str(db_path) if db_path else None
    def stop_coordinator():
        server.shutdown()
        server.server_close()

        supervisor.register(
            "coordinator",
            target=server.serve_forever,
            shutdown=stop_coordinator,
        )
    coordinator_url = f"http://{host}:{port}"
    supervisor.start()
    _wait_for_health(coordinator_url)

    os.environ["OSINT_AGENT_COORDINATOR_URL"] = coordinator_url
    os.environ["OSINT_AGENT_COORDINATOR_TOKEN"] = token

    bridge_server = create_phantom_control_bridge_server(
    host=bridge_host,
    port=bridge_port,
    token=token,
    memory_db=memory_db,
)

def stop_bridge() -> None:
        bridge_server.shutdown()
        bridge_server.server_close()

supervisor.register(
        "bridge",
        target=bridge_server.serve_forever,
        shutdown=stop_bridge,
    )

bridge_url = f"http://{bridge_host}:{bridge_port}"
os.environ["OSINT_AGENT_BRIDGE_URL"] = bridge_url
os.environ["OSINT_AGENT_BRIDGE_TOKEN"] = token

for index in range(max(1, worker_count)):
        supervisor.register(f"worker-{index}", target=lambda c=coordinator_url, t=token: run_phantom_worker_agent(c, t, poll_interval=poll_interval, memory_db=memory_db), shutdown=None)

    # start all registered services (coordinator, bridge, workers)
supervisor.start()

try:
        if open_gui:
            gui_main()
        else:
            threading.Event().wait()
finally:
        supervisor.stop_all()