def get_rssi_for_source(device, source_uuid):
    """
    Drills into kismet.device.base.seenby to extract
    the last RSSI seen by a specific data source.
    Returns dBm int or None.
    """
    seenby = device.get("kismet.device.base.seenby", {})

    if source_uuid not in seenby:
        return None
    
    source_entry = seenby[source_uuid]

    signal = source_entry.get("kismet.common.seenby.signal", {})

    rssi = signal.get("kismet.common.signal.last_signal", None)

    if rssi == 0:
        return None
    
    return rssi

def extract_device_info(device, omni_uuid, cone_uuid):
    mac = device.get("kismet.device.base.macaddr", "??:??:??:??:??:??")
    manuf = device.get("kismet.device.base.manuf", "Unknown")
    dev_type = device.get("kismet.device.base.type", "unknown")

    omni_rssi = get_rssi_for_source(device, omni_uuid)
    cone_rssi = get_rssi_for_source(device, cone_uuid)

    in_cone, confidence = compute_cone_status(omni_rssi, cone_rssi)

    return {
        "mac": mac,
        "manuf": manuf[:14],
        "type": dev_type,
        "omni_rssi": omni_rssi,
        "cone_rssi": cone_rssi,
        "in_cone": in_cone,
        "confidence": confidence
    }

def compute_cone_status(omni_rssi, cone_rssi, threshold_db=6):
    """
    Returns (in_cone: bool, confidence: float 0.0-1.0)
    
    threshold_db: minimum delta to classify as in-cone
    6 dBm is conservative (halved power), 10 dBm is strict.
    Start at 6 and then tune based on your antenna's beamwidth.
    """
    if cone_rssi is None:
        return False, 0.0
    
    if omni_rssi is None:
        return True, 0.0
    
    delta = cone_rssi - omni_rssi

    if delta >= threshold_db:
        confidence = min(1.0, (delta - threshold_db) / 9.0 +.5)
        return True, round(confidence, 2)
    
    return False, 0.0