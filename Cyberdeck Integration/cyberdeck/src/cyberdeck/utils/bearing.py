import math
def circular_mean(headings, weights):
    total_weight = sum(weights)
    sin_sum = sum(w * math.sin(math.radians(h))
                  for w, h in zip(weights, headings))
    cos_sum = sum(w * math.cos(math.radians(h))
                  for w, h in zip(weights, headings))
    bearing = math.degrees(math.atan2(sin_sum / total_weight,
                                      cos_sum / total_weight))
    return round(bearing % 360, 1)


def quaternion_to_heading(qw, qx, qy, qz) -> float:
    """Returns heading in degrees 0-360."""

    siny_cosp = 2.0*(qw*qz + qx*qy)
    cosy_cosp = 1.0 - 2.0*(qy*qy + qz*qz)
    yaw_rad = math.atan2(siny_cosp, cosy_cosp)
    heading = math.degrees(yaw_rad) % 360
    return round(heading,1)