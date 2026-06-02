from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional


class ServiceRecord:
    def __init__(self, name: str, target: Callable[..., None], shutdown: Optional[Callable[[], None]] = None, args=(), kwargs=None):
        self.name = name
        self.target = target
        self.shutdown = shutdown
        self.args = args
        self.kwargs = kwargs or {}
        self.thread: Optional[threading.Thread] = None
        self._restart_count = 0


class Supervisor:
    def __init__(self, max_restarts: int = 3, restart_backoff: float = 1.0):
        self._services: Dict[str, ServiceRecord] = {}
        self._stop_event = threading.Event()
        self.max_restarts = max_restarts
        self.restart_backoff = restart_backoff
        self._monitor_thread: Optional[threading.Thread] = None

    def register(self, name: str, target: Callable[..., None], shutdown: Optional[Callable[[], None]] = None, args=(), kwargs=None) -> None:
        self._services[name] = ServiceRecord(name, target, shutdown, args=args, kwargs=kwargs)

    def start(self) -> None:
        for rec in self._services.values():
            self._start_service(rec)
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _start_service(self, rec: ServiceRecord) -> None:
        rec.thread = threading.Thread(target=rec.target, args=rec.args, kwargs=rec.kwargs, daemon=True)
        rec.thread.start()
        rec._restart_count = 0

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            for rec in list(self._services.values()):
                thr = rec.thread
                if thr is None:
                    continue
                if not thr.is_alive():
                    rec._restart_count += 1
                    if rec._restart_count > self.max_restarts:
                        continue
                    time.sleep(self.restart_backoff)
                    rec.thread = threading.Thread(target=rec.target, args=rec.args, kwargs=rec.kwargs, daemon=True)
                    rec.thread.start()
            time.sleep(0.5)

    def stop_all(self) -> None:
        self._stop_event.set()
        # call shutdown hooks
        for rec in self._services.values():
            try:
                if rec.shutdown:
                    rec.shutdown()
            except Exception:
                pass
        # give threads a moment to exit
        time.sleep(0.2)


__all__ = ["Supervisor"]
