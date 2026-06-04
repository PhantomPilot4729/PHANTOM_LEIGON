import time
from typing import Callable, Optional

from .signal import extract_device_info
from .tracker import DeviceTracker
from .filters import apply_all_filters

class CorrelationDaemon:
    """
    Main correlation loop. Polls Kismet for recent devices, extracts
    per-source RSSI, applies filters, updates DeviceTracker history,
    and pushes results to the display server.
 
    Designed to be the single consumer of IMUDaemon and KismetClient
    output, keeping main.py as a thin orchestrator.
    """
    def __init__(
            self,
            imu,
            kismet_client,
            display_server,
            omni_uuid: str,
            cone_uuid: str,
            threshold_db: int = 6,
            poll_interval: float = .5,
            max_age_seconds: int = 15,
            rssi_floor_dbm: int = -90,
            on_update: Optional[Callable] = None,
    ):
        self._imu = imu
        self._kismet = kismet_client
        self._display = display_server
        self._omni_uuid = omni_uuid
        self._cone_uuid = cone_uuid
        self._threshold_db = threshold_db
        self._poll_interval = poll_interval
        self._max_age_seconds = max_age_seconds
        self._rssi_floor_dbm = rssi_floor_dbm
        self._on_update = on_update

        self._trackers: dict[str, DeviceTracker] = {}

    def _get_or_create_tracker(self, mac: str) -> DeviceTracker:
        if mac not in self._trackers:
            self._trackers[mac] = DeviceTracker(mac)
        return self._trackers[mac]
    
    def correlate(self, devices: list, heading, pitch) -> list:
        raw_info = [
            extract_device_info(d, self._omni_uuid, self._cone_uuid)
            for d in devices
        ]

        filtered = apply_all_filters(
            raw_info,
            max_age_seconds = self._max_age_seconds,
            rssi_floor_dbm = self._rssi_floor_dbm
        )

        now = time.time()
        for device in filtered:
            tracker = self._get_or_create_tracker(device["mac"])
            tracker.record(
                heading=heading,
                pitch=pitch,
                cone_rssi=device["cone_rssi"],
                omni_rssi=device["omni_rssi"],
                in_cone=device["in_cone"],
                timestamp=now
            )

            device["estimated_bearing"] = tracker.estimated_bearing()

        return filtered
    
    def run(self) -> None:
        print("Correlation daemon running. Ctrl-C to stop.")

        while True:
            try:
                heading, pitch = self._imu.get_pose()
                devices = self._kismet.get_recent_devices(
                    since_seconds=self._max_age_seconds
                )
                results = self.correlate(devices, heading, pitch)

                cone_devices = [d for d in results if d["in_cone"]]
                ambient_count = len(results)

                self._display.push({
                    "heading": heading,
                    "pitch": pitch,
                    "ambient_count": ambient_count,
                    "cone_devices": cone_devices
                })

                if self._on_update:
                    self._on_update(results)

                if cone_devices:
                    targets = [
                        f"{d['manuf']}({d['cone_rssi']}dBm)"
                        for d in cone_devices
                    ]
                    print(f"[{heading}° ↕{pitch}°] CONE: {', '.join(targets)}")

            except KeyboardInterrupt:
                print("\nShutting down.")
                break
            except Exception as e:
                print(f"[Correlation] Loop error: {e}")
            
            time.sleep(self._poll_interval)