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