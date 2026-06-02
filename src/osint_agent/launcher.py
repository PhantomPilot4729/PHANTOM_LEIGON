# ── PATCH: added all missing imports ──────────────────────────────────────────
# Flake8 F821 fired on every name below because this file had zero imports.
# Standard library names (os, threading, Path) were used bare in the function
# body. Internal helpers were called without any import statement at all.
#
# ACTION REQUIRED before committing:
#   Run this from the repo root to confirm each module path is correct:
#     grep -r "def create_phantom_coordinator_server\
#              \|def create_phantom_control_bridge_server\
#              \|def run_phantom_worker_agent\
#              \|class Supervisor\
#              \|def _wait_for_health\
#              \|def gui_main" src/
#   Adjust the four internal imports below if the paths differ.
# ──────────────────────────────────────────────────────────────────────────────
#import os                          # F821 @ lines 44, 45, 68, 69
#import threading                   # F821 @ line 93
#from pathlib import Path           # F821 @ line 6  (type hint in signature)

#from osint_agent.coordinator import create_phantom_coordinator_server   # F821 @ line 19
#from osint_agent.bridge      import create_phantom_control_bridge_server # F821 @ line 50
#from osint_agent.worker      import run_phantom_worker_agent             # F821 @ line 77
#from osint_agent.supervisor  import Supervisor                           # F821 @ line 26
#from osint_agent.health      import _wait_for_health                     # F821 @ line 42
#from osint_agent.gui         import gui_main                             # F821 @ line 91
# ── END PATCH ─────────────────────────────────────────────────────────────────
import os
import threading
from pathlib import Path
from osint_agent.worker import create_phantom_coordinator_server
from osint_agent.bridge import create_phantom_control_bridge_server
from osint_agent.worker import run_phantom_worker_agent
from osint_agent.supervisor import Supervisor

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
    # -------------------------
    # Coordinator setup
    # -------------------------
    coordinator_db = str(db_path) if db_path else None

    server = create_phantom_coordinator_server(
        host=host,
        port=port,
        token=token,
        db_path=coordinator_db,
    )

    supervisor = Supervisor(max_restarts=3, restart_backoff=1.0)

    def stop_coordinator():
        server.shutdown()
        server.server_close()

    supervisor.register(
        "coordinator",
        target=server.serve_forever,
        shutdown=stop_coordinator,
    )

    coordinator_url = f"http://{host}:{port}"

    # IMPORTANT: coordinator must be running before health check works
    supervisor.start()
    _wait_for_health(coordinator_url)

    os.environ["OSINT_AGENT_COORDINATOR_URL"] = coordinator_url
    os.environ["OSINT_AGENT_COORDINATOR_TOKEN"] = token

    # -------------------------
    # Bridge setup
    # -------------------------
    bridge_server = create_phantom_control_bridge_server(
        host=bridge_host,
        port=bridge_port,
        token=token,
        memory_db=memory_db,
    )

    def stop_bridge():
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

    # -------------------------
    # Workers
    # -------------------------
    for index in range(max(1, worker_count)):
        supervisor.register(
            f"worker-{index}",
            target=lambda c=coordinator_url, t=token: run_phantom_worker_agent(
                c,
                t,
                poll_interval=poll_interval,
                memory_db=memory_db,
            ),
            shutdown=None,
        )

    # -------------------------
    # GUI / runtime
    # -------------------------
    try:
        if open_gui:
            gui_main()
        else:
            threading.Event().wait()
    finally:
        supervisor.stop_all()