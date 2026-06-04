import json, board, adafruit_bno055

def save_calibration(sensor, path: str = "bno055_cal.json") -> None:
    """Call this once after achieving full calibration (all 3/3)."""
    data = {
        "offsets_accel":    list(sensor.offsets_accelerometer),
        "offsets_mag":      list(sensor.offsets_magnetometer),
        "offsets_gyro":     list(sensor.offsets_gyroscope),
        "radius_accel":     sensor.radius_accelerometer,
        "radius_mag":       sensor.radius_magnetometer,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Calibration saved to {path}")


def load_calibration(sensor, path: str = "bno055_cal.json") -> bool:
    """
    Returns True if offsets were loaded, False if file not found.
    The sensor must be in CONFIG mode to write offsets; the library
    handles this automatically via the property setters.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"No calibration file at {path} — run full calibration.")
        return False
    
    sensor.offsets_accelerometer = tuple(data["offsets_accel"])
    sensor.offsets_magnetometer  = tuple(data["offsets_mag"])
    sensor.offsets_gyroscope     = tuple(data["offsets_gyro"])
    sensor.radius_accelerometer  = data["radius_accel"]
    sensor.radius_magnetometer   = data["radius_mag"]
    
    print(f"Calibration loaded from {path}")
    return True


# Usage
i2c = board.I2C()
sensor = adafruit_bno055.BNO055_I2C(i2c)

if not load_calibration(sensor):
    input("Run calibration gestures, press Enter when done...")
    save_calibration(sensor)