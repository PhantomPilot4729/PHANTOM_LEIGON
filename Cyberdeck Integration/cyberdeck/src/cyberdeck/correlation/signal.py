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