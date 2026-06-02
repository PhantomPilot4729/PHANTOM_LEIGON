from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from urllib import request as urllib_request

from .gui import main as gui_main
from .worker import create_phantom_coordinator_server, run_phantom_worker_agent


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
    open_gui: bool = True,
) -> None:
    coordinator_db = str(db_path) if db_path else None
    server = create_phantom_coordinator_server(host=host, port=port, token=token, db_path=coordinator_db)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    coordinator_url = f"http://{host}:{port}"
    _wait_for_health(coordinator_url)

    os.environ["OSINT_AGENT_COORDINATOR_URL"] = coordinator_url
    os.environ["OSINT_AGENT_COORDINATOR_TOKEN"] = token

    worker_threads: list[threading.Thread] = []
    for _ in range(max(1, worker_count)):
        worker_thread = threading.Thread(
            target=run_phantom_worker_agent,
            args=(coordinator_url, token),
            kwargs={"poll_interval": poll_interval, "memory_db": memory_db},
            daemon=True,
        )
        worker_thread.start()
        worker_threads.append(worker_thread)

    try:
        if open_gui:
            gui_main()
        else:
            threading.Event().wait()
    finally:
        server.shutdown()
        server.server_close()