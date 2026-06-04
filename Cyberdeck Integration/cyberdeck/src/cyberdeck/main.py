import time
from cyberdeck.imu import IMUDaemon
from cyberdeck.kismet import KismetClient
from correlation import correlate
from cyberdeck.display import DisplayServer
from .correlation.daemon import CorrelationDaemon

KISMET_URL = "http://localhost:2501"
KISMET_AUTH = ("kismet", "your_password_here")
THRESHOLD_DB = 6
POLL_INTERVAL = 0.5 # seconds

imu = IMUDaemon()
kismet = KismetClient(KISMET_URL, KISMET_AUTH)
display = DisplayServer()

uuids = kismet.get_source_uuids()
OMNI_UUID = uuids["omni"]
CONE_UUID = uuids["cone"]

correlation = CorrelationDaemon(
    imu, kismet, display,
    omni_uuid=OMNI_UUID,
    cone_uuid=CONE_UUID,
    threshold_db=THRESHOLD_DB,
    poll_interval=POLL_INTERVAL
)
correlation.run()

print(f"Omni UUID: {OMNI_UUID}")
print(f"Cone UUID: {CONE_UUID}")
print("Running. Ctrl-C to stop.")

while True:
    try:
        heading, pitch = imu.get_pose()
        devices = kismet.get_recent_devices(since_seconds=15)
        results = correlate(devices, OMNI_UUID, CONE_UUID,
                            threshold_db=THRESHOLD_DB,
                            heading=heading, pitch=pitch)
        cone_devices = [d for d in results if d["in_cone"]]
        ambient_count = len(results)

        display.push({
            "heading": heading,
            "pitch": pitch,
            "ambient_count": ambient_count,
            "cone_devices": cone_devices,
        })

        if cone_devices:
            targets = [f"{d['manuf']}({d['cone_rssi']}dBm)"
                       for d in cone_devices]
            print(f"[{heading}° ↕{pitch}°] CONE: {', '.join(targets)}")
    except KeyboardInterrupt:
        print("\nShutting down.")
        break
    except Exception as e:
        print(f"Loop error: {e}")

    time.sleep(POLL_INTERVAL)