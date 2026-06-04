"""
rf – directional antenna signal processing package.
 
Exports:
    compute_cone_status – compare omni vs cone RSSI to determine if target is in beam
    # TODO: add exports from daemon, filters, tracker once implemented
"""
from .signal import compute_cone_status

__all__ = ["compute_cone_status"]