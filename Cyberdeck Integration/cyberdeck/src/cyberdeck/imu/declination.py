DECLINATION_DEG = 11.0

def true_heading(magnetic_heading: float) -> float:
    return (magnetic_heading - DECLINATION_DEG) % 360