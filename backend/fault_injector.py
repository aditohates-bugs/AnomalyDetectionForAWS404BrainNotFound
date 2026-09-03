"""
Fault Injector Module — Synthetic Anomaly Injection Engine
============================================================
Injects synthetic sensor corruption into live weather streams for live demo triggers.
Corruptions are calibrated to cross detector thresholds with high confidence:
  - spike         : +18.5°C unphysical rate-of-change jump
  - dropout       : NaN telemetry signal loss
  - inconsistency : 42.0°C temp + 98.0% humidity dew-point thermodynamic violation
  - spatial_outlier: +4.0°C spatial divergence offset from neighbors
  - frozen        : 30.0°C sensor flatline
  - drift         : +4.5°C monotonic calibration stray
"""

import numpy as np
from typing import Dict, Optional
from detector.detector import Reading


class FaultInjector:
    def __init__(self):
        self.pending_faults: Dict[str, str] = {}  # {station_id: fault_type}

    def trigger_fault(self, station_id: str, fault_type: str):
        """Queue a fault injection for the next live polling tick."""
        self.pending_faults[station_id] = fault_type.lower()

    def get_pending_fault(self, station_id: str) -> Optional[str]:
        return self.pending_faults.get(station_id)

    def clear_fault(self, station_id: str):
        if station_id in self.pending_faults:
            del self.pending_faults[station_id]

    def corrupt(self, r: Reading, fault_type: str) -> Reading:
        """Applies synthetic corruption to a Reading object."""
        fault_type = fault_type.lower()
        
        if fault_type == "spike":
            r.temperature += 18.5
        elif fault_type == "dropout":
            r.temperature = np.nan
            r.humidity = np.nan
            r.pressure = np.nan
        elif fault_type == "inconsistency":
            r.temperature = 42.0
            r.humidity = 98.0
        elif fault_type == "spatial_outlier":
            r.temperature += 4.0
        elif fault_type == "frozen":
            r.temperature = 30.0
            r.humidity = 70.0
            r.pressure = 980.0
        elif fault_type == "drift":
            r.temperature += 4.5
            
        return r
