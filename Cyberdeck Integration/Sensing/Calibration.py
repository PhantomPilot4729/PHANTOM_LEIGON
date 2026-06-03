import board, adafruit_bno055, time

i2c = board.I2C()
sensor = adafruit_bno055_I2C(i2c)

while True:
    sys, gyro, accel, mag = sensor.calibration_status
    print(f"Sys:{sys} Gyro:{gyro} Accel:{accel} Mag:{mag}")
    if all(v == 3 for v in (sys, gyro, accel, mag)):
        print("Fully calibrated")

        offsets = sensor.offsets_magnetometer
        break
    time.sleep(.5)