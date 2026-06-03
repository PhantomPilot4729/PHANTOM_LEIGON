from collections import deque
import statistics

class DeviceTracker:
    def __init__(self, mac, histor_size=20):
        self.mac = mac
        self.observations = deque(maxlen=history_size)

    def record(self, heading, pitch, cone_rssi, omni_rssi, in_cone, timestamp):
        self.observations.append({
            "heading": heading,
            "pitch": pitch,
            "cone_rssi": cone_rssi,
            "omni_rssi": omni_rssi,
            "in_cone": in_cone,
            "ts": timestamp
        })
    
    def estimated_bearing(self):
        """
        Weighted average of headings during confirmed cone sightings,
        weighted by cone RSSI strength. 
        """
        cone_obs = [o for o in self.observations if o["in_cone"] and o["cone_rssi"]]
        if not cone_obs:
            return None
        
        weights = [10 ** (o["cone_rssi"]/10) for o in cone_obs]
        total_weight = sum(weights)

        import math
        sin_sum = sum(w * math.sin(math.radians(o["heading"]))
                      for w, o in zip(weights, cone_obs))
        cos_sum = sum(w * math.cos(math.radians(o["heading"]))
                      for w, o in zip(weights, cone_obs))
        
        bearing = math.degrees(math.atan2(sin_sum / total_weight,
                                          cos_sum / total_weight))
        return round(bearing % 360, 1)
    
    def last_seen_seconds(self, now):
        if not self.observations:
            return float('inf')
        return now - self.observations[-1]["ts"]