"""
Weather Station Anomaly Detector (Delhi-NCR Pilot)
==================================================
Layered checks stacked in order of cost/specificity:
  A. Sanity check       -> physically possible bounds & rate of change
  B. Climatology check  -> normal baseline for station at (hour, month)
  C. Cross-variable     -> temp / dew point / humidity / pressure relationship
  D. Spatial check      -> comparison against nearby station readings

Outputs complete contract schema with:
  station_id, timestamp, is_anomaly, anomaly_type, confidence, reason, corrected_value
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any


class AnomalyType(Enum):
    NONE = "normal"
    SPIKE = "spike"
    STUCK = "stuck_sensor"
    DRIFT = "drift"
    DROPOUT = "dropout"
    SPATIAL_OUTLIER = "spatial_outlier"  # broken sensor, not real weather
    INCONSISTENCY = "inconsistency"


@dataclass
class Reading:
    station_id: str
    timestamp: pd.Timestamp
    temperature: float  # Celsius
    pressure: float      # hPa
    humidity: float      # %
    lat: float = 0.0
    lon: float = 0.0


# ---- Region & Physics Thresholds ----
PHYSICAL_BOUNDS = {
    "temperature": (-10.0, 55.0),
    "pressure": (850.0, 1085.0),
    "humidity": (0.0, 100.0),
}

MAX_RATE_OF_CHANGE = {  # per minute
    "temperature": 0.15,   # ~9°C per hour max plausible rate of change
    "pressure": 0.20,      # ~12 hPa per hour max change
    "humidity": 0.50,      # ~30% per hour change
}


class WeatherAnomalyDetector:
    def __init__(self, station_history: dict, z_thresh: float = 3.0):
        """
        station_history: {station_id: DataFrame[timestamp, temperature, pressure, humidity]}
                          used to build the "normal for this time" baseline climatology.
        """
        self.station_history = station_history
        self.z_thresh = z_thresh
        self.climatology = self._build_climatology()

    def _build_climatology(self):
        clim = {}
        for sid, df in self.station_history.items():
            d = df.copy()
            if not isinstance(d["timestamp"].iloc[0], pd.Timestamp):
                d["timestamp"] = pd.to_datetime(d["timestamp"])
            d["hour"] = d["timestamp"].dt.hour
            d["month"] = d["timestamp"].dt.month
            grouped = d.groupby(["hour", "month"]).agg(
                temp_mean=("temperature", "mean"), temp_std=("temperature", "std"),
                pres_mean=("pressure", "mean"), pres_std=("pressure", "std"),
                hum_mean=("humidity", "mean"), hum_std=("humidity", "std"),
            )
            # fill 0 std with baseline min std to avoid division by zero
            grouped["temp_std"] = grouped["temp_std"].replace(0, 0.5).fillna(1.0)
            grouped["pres_std"] = grouped["pres_std"].replace(0, 0.5).fillna(1.0)
            grouped["hum_std"] = grouped["hum_std"].replace(0, 1.0).fillna(2.0)
            clim[sid] = grouped
        return clim

    def check_sanity(self, r: Reading, prev: Optional[Reading]):
        issues = []
        for field_name, (lo, hi) in PHYSICAL_BOUNDS.items():
            val = getattr(r, field_name)
            if val is None or (isinstance(val, (float, np.floating)) and np.isnan(val)):
                issues.append(f"{field_name}_missing")
            elif not (lo <= val <= hi):
                issues.append(f"{field_name}_out_of_bounds")

        if prev is not None:
            dt_min = (r.timestamp - prev.timestamp).total_seconds() / 60.0
            if dt_min > 0 and dt_min < 180:  # within 3 hours
                for field_name, max_rate in MAX_RATE_OF_CHANGE.items():
                    val_curr = getattr(r, field_name)
                    val_prev = getattr(prev, field_name)
                    if (
                        val_curr is not None
                        and val_prev is not None
                        and not np.isnan(val_curr)
                        and not np.isnan(val_prev)
                    ):
                        delta = abs(val_curr - val_prev)
                        if delta / dt_min > max_rate:
                            issues.append(f"{field_name}_jump_too_fast")
        return issues

    def check_climatology(self, r: Reading):
        issues = []
        clim = self.climatology.get(r.station_id)
        if clim is None:
            return issues
        key = (r.timestamp.hour, r.timestamp.month)
        if key not in clim.index:
            return issues
        row = clim.loc[key]
        for field_name, mean_col, std_col in [
            ("temperature", "temp_mean", "temp_std"),
            ("pressure", "pres_mean", "pres_std"),
            ("humidity", "hum_mean", "hum_std"),
        ]:
            val = getattr(r, field_name)
            if val is None or (isinstance(val, (float, np.floating)) and np.isnan(val)):
                continue
            mean, std = row[mean_col], row[std_col]
            if std and std > 0:
                z = abs(val - mean) / std
                if z > self.z_thresh:
                    issues.append(f"{field_name}_climatology_outlier(z={z:.1f})")
        return issues

    def check_cross_variable(self, r: Reading):
        issues = []
        if (
            r.temperature is None
            or r.humidity is None
            or np.isnan(r.temperature)
            or np.isnan(r.humidity)
        ):
            return issues
        dew_point = self._approx_dew_point(r.temperature, r.humidity)
        if dew_point > r.temperature + 1.0:
            issues.append("dew_point_exceeds_temperature")
        if r.humidity < 5 and r.pressure is not None and not np.isnan(r.pressure) and r.pressure > 1040:
            issues.append("improbable_humidity_pressure_combo")
        # Check hot & near-saturation humidity without precipitation signal
        if r.temperature > 38.0 and r.humidity > 95.0:
            issues.append("extreme_heat_and_near_saturation_inconsistency")
        return issues

    @staticmethod
    def _approx_dew_point(temp_c, rh):
        a, b = 17.62, 243.12
        rh = max(rh, 0.1)
        gamma = (a * temp_c) / (b + temp_c) + np.log(rh / 100.0)
        return (b * gamma) / (a - gamma)

    def check_spatial(self, r: Reading, neighbor_readings: list):
        issues = []
        if len(neighbor_readings) < 2:
            return issues
        for field_name in ["temperature", "pressure", "humidity"]:
            this_val = getattr(r, field_name)
            if this_val is None or (isinstance(this_val, (float, np.floating)) and np.isnan(this_val)):
                continue
            vals = np.array([getattr(n, field_name) for n in neighbor_readings if getattr(n, field_name) is not None and not np.isnan(getattr(n, field_name))])
            if len(vals) < 2:
                continue
            n_mean, n_std = vals.mean(), vals.std()
            if n_std < (abs(n_mean) * 0.05 + 1.0) and abs(this_val - n_mean) > max(3.0 * n_std, 3.0):
                issues.append(f"{field_name}_spatial_outlier")
        return issues

    def check_frozen(self, r: Reading, recent_window: list):
        issues = []
        if len(recent_window) >= 3:
            t_vals = [w.temperature for w in recent_window[-3:] if w.temperature is not None and not np.isnan(w.temperature)]
            if r.temperature is not None and not np.isnan(r.temperature):
                t_vals.append(r.temperature)
            if len(t_vals) >= 4 and (max(t_vals) - min(t_vals)) < 0.001:
                issues.append("frozen_sensor_flatline")
        return issues

    def check_drift(self, r: Reading, recent_window: list, neighbor_readings: list):
        issues = []
        if len(recent_window) >= 4:
            z_scores = [self._climatology_z(w) for w in recent_window[-4:]] + [self._climatology_z(r)]
            z_scores = [z for z in z_scores if z is not None]
            if len(z_scores) >= 4 and self._is_monotonic_increasing(z_scores, tol=0.02):
                issues.append("monotonic_climatology_drift")

            if neighbor_readings and r.temperature is not None and not np.isnan(r.temperature):
                n_temps = [n.temperature for n in neighbor_readings if n.temperature is not None and not np.isnan(n.temperature)]
                if n_temps:
                    n_mean = float(np.mean(n_temps))
                    diff = r.temperature - n_mean
                    if abs(diff) > 1.8:
                        issues.append("spatial_divergence_drift")
        return issues

    def evaluate(
        self,
        r: Reading,
        prev: Optional[Reading] = None,
        neighbor_readings: Optional[list] = None,
        recent_window: Optional[list] = None,
    ) -> Dict[str, Any]:
        if neighbor_readings is None:
            neighbor_readings = []
        if recent_window is None:
            recent_window = []

        sanity_issues = self.check_sanity(r, prev)
        clim_issues = self.check_climatology(r)
        cross_issues = self.check_cross_variable(r)
        spatial_issues = self.check_spatial(r, neighbor_readings)
        frozen_issues = self.check_frozen(r, recent_window)
        drift_issues = self.check_drift(r, recent_window, neighbor_readings)

        all_issues = sanity_issues + clim_issues + cross_issues + spatial_issues + frozen_issues + drift_issues
        is_anomaly = len(all_issues) > 0

        anomaly_type = AnomalyType.NONE
        if is_anomaly:
            anomaly_type = self.classify(
                r, prev, recent_window, spatial_issues, sanity_issues, clim_issues, cross_issues, frozen_issues, drift_issues
            )

        confidence = self._compute_confidence(
            is_anomaly, anomaly_type, all_issues, r, neighbor_readings, recent_window
        )
        reason = self._generate_reason(
            is_anomaly, anomaly_type, all_issues, r, neighbor_readings, sanity_issues, clim_issues, cross_issues, spatial_issues
        )
        corrected_val = self._compute_corrected_value(
            is_anomaly, anomaly_type, all_issues, r, neighbor_readings, recent_window
        )

        ts_str = r.timestamp.isoformat() if hasattr(r.timestamp, "isoformat") else str(r.timestamp)

        return {
            "station_id": r.station_id,
            "timestamp": ts_str,
            "is_anomaly": is_anomaly,
            "anomaly_type": anomaly_type.value,
            "confidence": confidence,
            "reason": reason,
            "corrected_value": corrected_val,
        }

    def classify(
        self,
        r: Reading,
        prev: Optional[Reading],
        recent_window: list,
        spatial_issues: list,
        sanity_issues: list,
        clim_issues: list,
        cross_issues: list,
        frozen_issues: Optional[list] = None,
        drift_issues: Optional[list] = None,
    ) -> AnomalyType:
        if frozen_issues is None:
            frozen_issues = []
        if drift_issues is None:
            drift_issues = []

        # Dropout check
        if any("missing" in s for s in sanity_issues):
            return AnomalyType.DROPOUT

        if prev is not None:
            gap_min = (r.timestamp - prev.timestamp).total_seconds() / 60.0
            if gap_min > 3 * self._expected_interval_min(recent_window):
                return AnomalyType.DROPOUT

        # Stuck sensor check
        if frozen_issues or len(recent_window) >= 3:
            recent_t = [x.temperature for x in recent_window[-3:] if x.temperature is not None and not np.isnan(x.temperature)]
            if r.temperature is not None and not np.isnan(r.temperature):
                recent_t.append(r.temperature)
            if len(recent_t) >= 4 and max(recent_t) - min(recent_t) < 0.001:
                return AnomalyType.STUCK
            if frozen_issues:
                return AnomalyType.STUCK

        # Spike check
        if any("jump_too_fast" in s for s in sanity_issues) or any("out_of_bounds" in s for s in sanity_issues):
            return AnomalyType.SPIKE

        # Drift check
        if drift_issues:
            return AnomalyType.DRIFT

        if len(recent_window) >= 4:
            devs = [self._climatology_z(x) for x in recent_window[-4:]] + [self._climatology_z(r)]
            devs = [d for d in devs if d is not None]
            if len(devs) >= 4 and self._is_monotonic_increasing(devs):
                return AnomalyType.DRIFT

        # Cross-variable / Inconsistency check
        if cross_issues and not spatial_issues:
            return AnomalyType.INCONSISTENCY

        # Spatial outlier check
        if spatial_issues:
            return AnomalyType.SPATIAL_OUTLIER

        if clim_issues:
            return AnomalyType.SPIKE

        return AnomalyType.SPIKE

    def _compute_confidence(
        self,
        is_anomaly: bool,
        anomaly_type: AnomalyType,
        all_issues: list,
        r: Reading,
        neighbor_readings: list,
        recent_window: list,
    ) -> float:
        if not is_anomaly:
            return 0.0

        if anomaly_type == AnomalyType.DROPOUT:
            return 0.99

        if anomaly_type == AnomalyType.STUCK:
            return 0.96

        # Calculate max z-score found in issue strings
        max_z = 3.0
        for issue in all_issues:
            if "z=" in issue:
                try:
                    z_val = float(issue.split("z=")[1].split(")")[0])
                    max_z = max(max_z, z_val)
                except Exception:
                    pass

        # Base confidence calculation
        conf = 0.50 + 0.06 * len(all_issues) + 0.08 * (max_z - 3.0)
        if anomaly_type == AnomalyType.SPIKE and any("jump_too_fast" in s for s in all_issues):
            conf += 0.20
        if anomaly_type == AnomalyType.SPATIAL_OUTLIER:
            conf += 0.15

        return round(float(min(0.99, max(0.65, conf))), 2)

    def _generate_reason(
        self,
        is_anomaly: bool,
        anomaly_type: AnomalyType,
        all_issues: list,
        r: Reading,
        neighbor_readings: list,
        sanity_issues: list,
        clim_issues: list,
        cross_issues: list,
        spatial_issues: list,
    ) -> str:
        if not is_anomaly:
            return "All station sensor parameters operating within normal physical, climatological, and spatial bounds."

        parts = []

        # 1. Primary Parameter Cause
        if anomaly_type == AnomalyType.DROPOUT:
            parts.append("Telemetry signal lost or containing NaN values across sensor parameters.")
        elif anomaly_type == AnomalyType.STUCK:
            parts.append(f"Sensor output frozen at {r.temperature:.1f}°C across consecutive readings (stuck sensor condition).")
        elif anomaly_type == AnomalyType.DRIFT:
            parts.append("Temperature exhibited a continuous monotonic calibration drift relative to station baseline.")
        else:
            # Describe z-score or jump
            z_str = ""
            for issue in clim_issues:
                if "z=" in issue:
                    z_str = issue.split("(")[1].rstrip(")")
                    break
            if z_str:
                z_num = z_str.replace("z=", "")
                parts.append(f"Temperature deviated {z_num} std devs from the normal baseline for this hour")
            elif any("jump_too_fast" in s for s in sanity_issues):
                parts.append("Temperature experienced an unphysically rapid rate-of-change jump")
            elif any("out_of_bounds" in s for s in sanity_issues):
                parts.append("Reading exceeded hard physical environmental limits")
            elif cross_issues:
                parts.append("Sensor values violated thermodynamic dew point cross-variable constraints")
            else:
                parts.append("Parameter values deviated significantly from expected baseline")

        # 2. Secondary Parameters Context
        sec_normal = []
        if not any("pressure" in s for s in all_issues):
            sec_normal.append("pressure")
        if not any("humidity" in s for s in all_issues):
            sec_normal.append("humidity")

        if sec_normal and anomaly_type != AnomalyType.DROPOUT:
            if len(sec_normal) == 2:
                parts.append("pressure and humidity remained normal")
            else:
                parts.append(f"{sec_normal[0]} remained normal")

        # 3. Spatial Context
        if spatial_issues:
            parts.append("neighboring stations showed no correlated change.")
        elif neighbor_readings:
            parts.append("neighboring stations cross-validated normal regional weather trend.")

        # Format into crisp readable sentence
        clean_parts = [p.rstrip(".") for p in parts if p]
        text = "; ".join(clean_parts)
        if not text.endswith("."):
            text += "."
        # Capitalize first letter
        return text[0].upper() + text[1:]

    def _compute_corrected_value(
        self,
        is_anomaly: bool,
        anomaly_type: AnomalyType,
        all_issues: list,
        r: Reading,
        neighbor_readings: list,
        recent_window: list,
    ) -> Optional[Dict[str, float]]:
        if not is_anomaly:
            return None

        corrected = {}

        # Identify which fields need correction
        bad_fields = set()
        if anomaly_type in (AnomalyType.DROPOUT, AnomalyType.STUCK, AnomalyType.DRIFT, AnomalyType.SPIKE):
            bad_fields.add("temperature")
        for issue in all_issues:
            if "pressure" in issue:
                bad_fields.add("pressure")
            if "humidity" in issue:
                bad_fields.add("humidity")
            if "temperature" in issue:
                bad_fields.add("temperature")

        if not bad_fields:
            bad_fields.add("temperature")

        for field in bad_fields:
            # Strategy A: Neighbor spatial consensus
            valid_neighbors = [
                getattr(n, field)
                for n in neighbor_readings
                if getattr(n, field) is not None and not np.isnan(getattr(n, field))
            ]
            if valid_neighbors:
                val = float(np.median(valid_neighbors))
                corrected[field] = round(val, 1)
            else:
                # Strategy B: Temporal trend / rolling median from recent window
                valid_recent = [
                    getattr(w, field)
                    for w in recent_window
                    if getattr(w, field) is not None and not np.isnan(getattr(w, field))
                ]
                if valid_recent:
                    val = float(np.median(valid_recent[-3:]))
                    corrected[field] = round(val, 1)
                else:
                    # Fallback to climatology mean
                    clim = self.climatology.get(r.station_id)
                    if clim is not None:
                        key = (r.timestamp.hour, r.timestamp.month)
                        if key in clim.index:
                            mean_col = f"{field[:4]}_mean" if field != "temperature" else "temp_mean"
                            val = float(clim.loc[key, mean_col])
                            corrected[field] = round(val, 1)

        return corrected if corrected else None

    def _expected_interval_min(self, recent_window: list):
        if len(recent_window) < 2:
            return 15
        deltas = [
            (recent_window[i + 1].timestamp - recent_window[i].timestamp).total_seconds() / 60
            for i in range(len(recent_window) - 1)
        ]
        return np.median(deltas) if deltas else 15

    def _climatology_z(self, r: Reading):
        clim = self.climatology.get(r.station_id)
        if clim is None or r.temperature is None or np.isnan(r.temperature):
            return None
        key = (r.timestamp.hour, r.timestamp.month)
        if key not in clim.index:
            return None
        row = clim.loc[key]
        mean, std = row["temp_mean"], row["temp_std"]
        if not std or std == 0:
            return None
        return (r.temperature - mean) / std

    @staticmethod
    def _is_monotonic_increasing(vals, tol=0.05):
        diffs = np.diff(vals)
        return bool(np.all(diffs > -tol) and (vals[-1] - vals[0]) > 0.4)


if __name__ == "__main__":
    from data_loader import load_delhi_station_data

    station_data = load_delhi_station_data()
    detector = WeatherAnomalyDetector(station_history=station_data)

    print("\n--- Testing Single Reading Contract Output ---")
    st_id = "igi_airport"
    sample_df = station_data[st_id]
    r_test = Reading(
        station_id=st_id,
        timestamp=sample_df.iloc[100]["timestamp"],
        temperature=sample_df.iloc[100]["temperature"] + 18.5,  # Injected spike
        pressure=sample_df.iloc[100]["pressure"],
        humidity=sample_df.iloc[100]["humidity"],
        lat=sample_df.iloc[100]["lat"],
        lon=sample_df.iloc[100]["lon"],
    )

    prev_test = Reading(
        station_id=st_id,
        timestamp=sample_df.iloc[99]["timestamp"],
        temperature=sample_df.iloc[99]["temperature"],
        pressure=sample_df.iloc[99]["pressure"],
        humidity=sample_df.iloc[99]["humidity"],
    )

    neighbors = [
        Reading(
            station_id=other_id,
            timestamp=sample_df.iloc[100]["timestamp"],
            temperature=station_data[other_id].iloc[100]["temperature"],
            pressure=station_data[other_id].iloc[100]["pressure"],
            humidity=station_data[other_id].iloc[100]["humidity"],
        )
        for other_id in station_data
        if other_id != st_id
    ]

    res = detector.evaluate(r_test, prev=prev_test, neighbor_readings=neighbors)
    import json
    print(json.dumps(res, indent=2))
