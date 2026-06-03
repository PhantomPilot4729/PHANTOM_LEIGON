import json

def save_calibration(sensor, path="imu_cal.json"):
    cal = {
        "offsets_mag": list(sensor.offsets_magnetometer),
        "offsets_gyro": list(sensor.offsets_gyroscope),
        "offsets_accel": list(sensor.offsets_accelerometer),
        "radius_mag": sensor.radius_magnetometer,
        "radius_accel": sensor.radius_accelerometer,
    }
    with open(path, "w") as f:
        json.dump(cal, f)

def load_calibration(sensor, path="imu_cal.json"):
    with open(path) as f:
        cal = json.load(f)
    sensor.offsets_magnetometer = tuple(cal["offsets_mag"])
    sensor.offsets_gyroscope = tuple(cal["offsets_gyro"])
    sensor.offsets_accelerometer = tuple(cal["offsets_accel"])
    sensor.radius_magnetometer = cal["radius_mag"]
    sensor.radius_acclerometer = cal["radius_accel"]
