"""Simple smoke test to verify coordinator and bridge health and run a preset.

Usage:
  python tools/smoke_run.py

Environment variables:
  OSINT_AGENT_COORDINATOR_URL (default: http://127.0.0.1:8780)
  OSINT_AGENT_BRIDGE_URL (default: http://127.0.0.1:8790)
  OSINT_AGENT_BRIDGE_TOKEN (default: phantom)

The script performs GET /health on both services and POST /preset/quick to the bridge.
"""
from __future__ import annotations

import os
import sys
import time

try:
    import requests
except Exception:  # pragma: no cover - requests may not be installed in CI
    print("The 'requests' package is required. Install it with: pip install requests")
    sys.exit(2)


def main() -> int:
    coord = os.environ.get("OSINT_AGENT_COORDINATOR_URL", "http://127.0.0.1:8780").rstrip("/")
    bridge = os.environ.get("OSINT_AGENT_BRIDGE_URL", "http://127.0.0.1:8790").rstrip("/")
    token = os.environ.get("OSINT_AGENT_BRIDGE_TOKEN", "phantom")

    print(f"Coordinator: {coord}")
    print(f"Bridge: {bridge}")

    try:
        r = requests.get(coord + "/health", timeout=3)
        print("Coordinator /health:", r.status_code, r.text.strip())
    except Exception as exc:
        print("Coordinator health check failed:", exc)
        return 1

    try:
        r = requests.get(bridge + "/health", timeout=3)
        print("Bridge /health:", r.status_code, r.text.strip())
    except Exception as exc:
        print("Bridge health check failed:", exc)
        return 2

    # Trigger quick preset
    headers = {"X-Phantom-Token": token}
    try:
        r = requests.post(bridge + "/preset/quick", headers=headers, timeout=5)
        print("POST /preset/quick ->", r.status_code, r.text.strip())
        if r.status_code not in (200, 202):
            return 3
    except Exception as exc:
        print("Preset request failed:", exc)
        return 4

    print("Smoke test completed — preset queued. Poll bridge /job/<id> to follow progress.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
