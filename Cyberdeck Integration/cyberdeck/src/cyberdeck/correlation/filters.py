import time

DEFAULT_VENDOR_BLOCKLIST = {
    "Raspberry Pi",
    "Intel",
    "Espressif"
}

def filter_by_age(devices: list, max_seconds: int = 15) -> list:
    cutoff = time.time()-max_seconds
    return [
        d for d in devices
        if d.get("kismet.device.base.last_time",0) >= cutoff
    ]

def filter_by_rssi(devices: list, floor_dbm: int = -90) -> list:
    def above_floor(d):
        omni = d.get("omni_rssi")
        cone = d.get("cone_rssi")
        if omni is not None and omni >= floor_dbm:
            return True
        if cone is not None and cone >= floor_dbm:
            return True
        return False
    
    return [d for d in devices if above_floor(d)]

def filter_by_venor(devices: list, blocklist: set = DEFAULT_VENDOR_BLOCKLIST) -> list:
    def not_blocked(d):
        manuf = d.get("manuf", d.get("kismet.device.base.manuf","")).lower()
        return not any(blocked.lower() in manuf for blocked in blocklist)
    
    return [d for d in devices if not_blocked(d)]

def apply_all_filters(
        devices: list,
        max_age_seconds: int = 15,
        rssi_floor_dbm: int = -90,
        vendor_blocklist: set = DEFAULT_VENDOR_BLOCKLIST,
) -> list:
    devices = filter_by_age(devices, max_age_seconds)
    devices = filter_by_rssi(devices, rssi_floor_dbm)
    devices = filter_by_venor(devices, vendor_blocklist)
    return devices