"""
imu - BNO055 heading/pitch package.

Exports:
    IMUDaemon - background-thread sensor wrapper (heading + pitch)
    get_declination - lookup magnetic declination for a lat/lon
"""

from .daemon import IMUDaemon
from .declination import get_declination

__all__ = ["IMUDaemon", "get_declination"]