"""
Weather Station Anomaly Detector (Delhi-NCR Pilot) — Upgraded Core
===================================================================
Integrated 4-Layer AWS Anomaly Detection Engine:
  A. Sanity Check           -> physically possible bounds & rate of change
  B & C. LSTM-Autoencoder  -> learned 24-hour neural dynamics & cross-variable baseline
  D. Spatial Consensus      -> neighbor anomaly-score & value cross-validation

Solves the "normalcy problem" using:
  - Graded severity scoring (unusualness score)
  - Neighbor reconstruction-score spatial correlation check
  - Historical extreme weather window adaptation
  - Strict production contract output (`evaluate()`)
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
import torch
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any

# Ensure detector directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lstm_autoencoder import (
    LSTMAutoencoder, PerStationScaler, STATION_INDEX, STATION_IDS,
    WINDOW_SIZE, NUM_STATIONS, NUM_FEATURES, INPUT_DIM
)


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
    "temperature": 0.25,   # ~15°C per hour max plausible rate of change (haboob/squall)
    "pressure": 0.25,      # ~15 hPa per hour max change
    "humidity": 0.80,      # ~48% per hour change (thunderstorm downdraft)
}


class CustomUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if name == "PerStationScaler":
            from lstm_autoencoder import PerStationScaler
            return PerStationScaler
        return super().find_class(module, name)


class WeatherAnomalyDetector:
    def __init__(
        self,
        station_history: dict,
        z_thresh: float = 3.0,
        model_path: str = "detector/lstm_ae_model.pth",
        config_path: str = "detector/lstm_ae_config.pkl"
    ):
        """
        station_history: {station_id: DataFrame[timestamp, temperature, pressure, humidity]}
        """
        self.station_history = station_history
        self.z_thresh = z_thresh
        self.climatology = self._build_climatology()

        # Load PyTorch LSTM-Autoencoder Engine if available
        self.use_lstm = False
        self.model = None
        self.scaler = None
        self.thresholds = {}
        self._lstm_cache = {}

        if os.path.exists(model_path) and os.path.exists(config_path):
            try:
                with open(config_path, "rb") as f:
                    config = CustomUnpickler(f).load()
                self.scaler = config["scaler"]
                self.thresholds = config["thresholds"]

                self.model = LSTMAutoencoder(input_dim=INPUT_DIM, hidden_dim=32, num_layers=1)
                self.model.load_state_dict(torch.load(model_path, map_location=torch.device("cpu")))
                self.model.eval()
                self.use_lstm = True
                print(" Successfully loaded PyTorch LSTM-Autoencoder anomaly core.")
            except Exception as e:
                print(f" Warning: Could not load LSTM-AE model ({e}). Falling back to Climatology Z-Score core.")

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

    def _climatology_z(self, r: Reading) -> Optional[float]:
        clim = self.climatology.get(r.station_id)
        if clim is None: return None
        key = (r.timestamp.hour, r.timestamp.month)
        if key not in clim.index: return None
        row = clim.loc[key]
        if r.temperature is None or np.isnan(r.temperature): return None
        return abs(r.temperature - row["temp_mean"]) / row["temp_std"]

    def _is_monotonic_increasing(self, vals: List[float], tol: float = 0.05) -> bool:
        if len(vals) < 4:
            return False
        # Require actual monotonic growth (end value >= start value + 0.8) to distinguish drift from flatline/steady offset
        return (vals[-1] - vals[0] >= 0.8) and all(vals[i] >= vals[i - 1] - tol for i in range(1, len(vals)))

    def _expected_interval_min(self, recent_window: list) -> float:
        if len(recent_window) < 2: return 15.0
        diffs = [(recent_window[i].timestamp - recent_window[i-1].timestamp).total_seconds() / 60.0 for i in range(1, len(recent_window))]
        return float(np.median(diffs))

    def check_drift(self, r: Reading, recent_window: list, neighbor_readings: list):
        issues = []
        if len(recent_window) >= 3:
            z_scores = [self._climatology_z(w) for w in recent_window[-3:]] + [self._climatology_z(r)]
            z_scores = [z for z in z_scores if z is not None]
            # Require 4 consecutive timesteps with monotonic climatology deviation and |z| >= 1.0
            if len(z_scores) >= 4 and self._is_monotonic_increasing(z_scores, tol=0.01):
                if abs(z_scores[-1]) >= 1.0:
                    issues.append("monotonic_climatology_drift")

            if neighbor_readings and r.temperature is not None and not np.isnan(r.temperature):
                n_temps = [n.temperature for n in neighbor_readings if n.temperature is not None and not np.isnan(n.temperature)]
                if n_temps:
                    n_mean = float(np.mean(n_temps))
                    diff = r.temperature - n_mean
                    if abs(diff) > 1.8:
                        issues.append("spatial_divergence_drift")
        return issues

    def _compute_lstm_unusualness(self, r: Reading, recent_window: list) -> Dict[str, Any]:
        """Runs rolling 24-hour sequence through LSTM-AE to compute unusualness score and feature errors."""
        if not self.use_lstm or self.model is None or self.scaler is None:
            return {"unusualness": 0.0, "mse": 0.0, "temp_err": 0.0, "pres_err": 0.0, "hum_err": 0.0}

        cache_key = (r.station_id, str(r.timestamp), round(float(r.temperature or 0.0), 2), round(float(r.humidity or 0.0), 2))
        if hasattr(self, "_lstm_cache") and cache_key in self._lstm_cache:
            return self._lstm_cache[cache_key]

        sid = r.station_id
        st_idx = STATION_INDEX.get(sid, 0)
        one_hot = np.zeros(NUM_STATIONS, dtype=np.float32)
        one_hot[st_idx] = 1.0

        # Construct 24-hour sequence
        seq_readings = recent_window[-(WINDOW_SIZE - 1):] + [r]
        while len(seq_readings) < WINDOW_SIZE:
            seq_readings.insert(0, seq_readings[0] if seq_readings else r)

        feats = []
        for w in seq_readings:
            t = w.temperature if w.temperature is not None and not np.isnan(w.temperature) else 25.0
            p = w.pressure if w.pressure is not None and not np.isnan(w.pressure) else 1000.0
            h = w.humidity if w.humidity is not None and not np.isnan(w.humidity) else 60.0
            norm_v = self.scaler.transform_row(sid, t, p, h)
            vec = np.concatenate([norm_v, one_hot])
            feats.append(vec)

        x_arr = np.array(feats, dtype=np.float32)  # (24, 13)
        x_tensor = torch.from_numpy(x_arr).unsqueeze(0)  # (1, 24, 13)
        y_target = x_tensor[:, :, :NUM_FEATURES]  # (1, 24, 3)

        with torch.no_grad():
            rec = self.model(x_tensor)  # (1, 24, 3)
            diff = (rec - y_target).squeeze(0).numpy()  # (24, 3)
            mse = float(np.mean(diff ** 2))

            temp_err = float(np.mean(diff[:, 0] ** 2))
            pres_err = float(np.mean(diff[:, 1] ** 2))
            hum_err = float(np.mean(diff[:, 2] ** 2))

        thresh = self.thresholds.get(sid, 0.015)
        unusualness = float(mse / thresh) if thresh > 0 else 0.0

        res = {
            "unusualness": unusualness,
            "mse": mse,
            "threshold": thresh,
            "temp_err": temp_err,
            "pres_err": pres_err,
            "hum_err": hum_err,
        }
        if hasattr(self, "_lstm_cache"):
            self._lstm_cache[cache_key] = res
        return res

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

        # LSTM-AE Evaluation
        lstm_res = self._compute_lstm_unusualness(r, recent_window)
        unusualness = lstm_res["unusualness"]

        # Compute Neighbor Anomaly Score Spatial Consensus
        neighbor_unusualness_scores = []
        if self.use_lstm and neighbor_readings:
            for n_r in neighbor_readings:
                n_res = self._compute_lstm_unusualness(n_r, [])
                neighbor_unusualness_scores.append(n_res["unusualness"])

        avg_neighbor_unusualness = (
            float(np.mean(neighbor_unusualness_scores)) if neighbor_unusualness_scores else 0.0
        )

        all_issues = sanity_issues + clim_issues + cross_issues + spatial_issues + frozen_issues + drift_issues

        # HARD PHYSICAL / HARDWARE FAULTS (Always trigger hard anomaly)
        has_hard_fault = (
            any("missing" in s for s in sanity_issues)
            or any("jump_too_fast" in s for s in sanity_issues)
            or any("out_of_bounds" in s for s in sanity_issues)
            or len(frozen_issues) > 0
            or len(cross_issues) > 0
        )

        # SOFT STATISTICAL / HEURISTIC SIGNALS
        clim_active = len(clim_issues) > 0
        spatial_active = len(spatial_issues) > 0
        drift_active = len(drift_issues) > 0
        lstm_active = (unusualness > 1.0)

        active_soft_layers = sum([clim_active, spatial_active, drift_active, lstm_active])

        # CORROBORATION DECISION RULE:
        # Require 2+ soft layers to corroborate OR single soft layer with strong amplitude
        if has_hard_fault:
            is_anomaly = True
        elif active_soft_layers >= 2:
            is_anomaly = True
        elif spatial_active and (unusualness > 0.65 or any("spatial_outlier" in s for s in spatial_issues)):
            is_anomaly = True
        elif drift_active and (unusualness > 0.65 or spatial_active or clim_active):
            is_anomaly = True
        elif unusualness > 1.6:
            is_anomaly = True
        else:
            is_anomaly = False

        # Apply Disaster Safeguard & Graded Severity:
        # If high unusualness is correlated across neighbor stations (regional extreme weather event)
        # AND no isolated hardware fault pattern (frozen, jump, dropout) exists -> Downgrade/Reclassify
        is_real_extreme_weather = False
        if is_anomaly and not has_hard_fault:
            if avg_neighbor_unusualness > 0.75:
                # Correlated regional event (e.g. monsoon cloudburst / severe heatwave)
                is_anomaly = False
                is_real_extreme_weather = True

        anomaly_type = AnomalyType.NONE
        if is_anomaly:
            anomaly_type = self.classify(
                r, prev, recent_window, spatial_issues, sanity_issues, clim_issues, cross_issues, frozen_issues, drift_issues, neighbor_readings
            )

        confidence = self._compute_confidence(
            is_anomaly, anomaly_type, all_issues, unusualness, r
        )

        reason = self._generate_reason(
            is_anomaly, anomaly_type, is_real_extreme_weather, all_issues, unusualness,
            avg_neighbor_unusualness, r, neighbor_readings, sanity_issues, clim_issues,
            cross_issues, spatial_issues, lstm_res
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
        neighbor_readings: Optional[list] = None,
    ) -> AnomalyType:
        if frozen_issues is None:
            frozen_issues = []
        if drift_issues is None:
            drift_issues = []
        if neighbor_readings is None:
            neighbor_readings = []

        # 1. Telemetry Dropout (Missing Signal / Gap)
        if any("missing" in s for s in sanity_issues) or r.temperature is None or (isinstance(r.temperature, (float, np.floating)) and np.isnan(r.temperature)):
            return AnomalyType.DROPOUT

        if prev is not None:
            gap_min = (r.timestamp - prev.timestamp).total_seconds() / 60.0
            if gap_min > 3 * self._expected_interval_min(recent_window):
                return AnomalyType.DROPOUT

        # 2. Hardware Stuck / Frozen Flatline
        if frozen_issues or len(recent_window) >= 2:
            recent_t = [x.temperature for x in recent_window[-2:] if x.temperature is not None and not np.isnan(x.temperature)]
            if r.temperature is not None and not np.isnan(r.temperature):
                recent_t.append(r.temperature)
            if len(recent_t) >= 3 and max(recent_t) - min(recent_t) < 0.001:
                return AnomalyType.STUCK
            if frozen_issues:
                return AnomalyType.STUCK

        # 3. Cross-Variable Thermodynamic Inconsistency (Dew Point / Heat-Saturation Impossible Combo)
        # Higher priority than spatial outlier!
        if cross_issues:
            return AnomalyType.INCONSISTENCY

        # 4. Spike / Rapid Rate-of-Change Jump / Extreme Single-Tick Excursion
        if any("jump_too_fast" in s for s in sanity_issues) or any("out_of_bounds" in s for s in sanity_issues):
            return AnomalyType.SPIKE

        if neighbor_readings and r.temperature is not None and not np.isnan(r.temperature):
            n_temps = [n.temperature for n in neighbor_readings if n.temperature is not None and not np.isnan(n.temperature)]
            if n_temps:
                n_mean = float(np.mean(n_temps))
                if abs(r.temperature - n_mean) >= 16.0:
                    return AnomalyType.SPIKE

        # 5. Sensor Calibration Drift (Multi-Hour Monotonic Climatology Drift)
        if any("monotonic_climatology_drift" in s for s in drift_issues):
            return AnomalyType.DRIFT

        if len(recent_window) >= 4:
            devs = [self._climatology_z(x) for x in recent_window[-4:]] + [self._climatology_z(r)]
            devs = [d for d in devs if d is not None]
            if len(devs) >= 4 and self._is_monotonic_increasing(devs):
                return AnomalyType.DRIFT

        # 6. Spatial Outlier (Fallback when sensor differs from spatial neighbors)
        if spatial_issues or any("spatial_divergence_drift" in s for s in drift_issues):
            return AnomalyType.SPATIAL_OUTLIER

        if clim_issues:
            return AnomalyType.SPIKE

        return AnomalyType.SPIKE

    def _compute_confidence(
        self,
        is_anomaly: bool,
        anomaly_type: AnomalyType,
        all_issues: list,
        unusualness: float,
        r: Reading,
    ) -> float:
        if not is_anomaly:
            return 0.0

        if anomaly_type == AnomalyType.DROPOUT:
            return 0.99

        if anomaly_type == AnomalyType.STUCK:
            return 0.96

        base_conf = 0.50 + 0.05 * len(all_issues) + 0.10 * max(0.0, unusualness - 1.0)
        if anomaly_type == AnomalyType.SPIKE and any("jump_too_fast" in s for s in all_issues):
            base_conf += 0.20
        if anomaly_type == AnomalyType.SPATIAL_OUTLIER:
            base_conf += 0.15

        return round(float(min(0.99, max(0.65, base_conf))), 2)

    def _generate_reason(
        self,
        is_anomaly: bool,
        anomaly_type: AnomalyType,
        is_real_extreme_weather: bool,
        all_issues: list,
        unusualness: float,
        avg_neighbor_unusualness: float,
        r: Reading,
        neighbor_readings: list,
        sanity_issues: list,
        clim_issues: list,
        cross_issues: list,
        spatial_issues: list,
        lstm_res: dict,
    ) -> str:
        if is_real_extreme_weather:
            return (
                f"Regional extreme weather event detected; station unusualness score ({unusualness:.1f}x threshold) "
                f"is strongly correlated across neighbor AWS stations ({avg_neighbor_unusualness:.1f}x threshold); "
                f"flagged for review, not classified as sensor fault."
            )

        if not is_anomaly:
            return "All station sensor parameters operating within normal physical, climatological, and spatial bounds."

        parts = []

        if anomaly_type == AnomalyType.DROPOUT:
            parts.append("Telemetry signal lost or containing NaN values across sensor parameters")
        elif anomaly_type == AnomalyType.STUCK:
            parts.append(f"Sensor output frozen at {r.temperature:.1f}°C across consecutive readings (stuck sensor condition)")
        elif anomaly_type == AnomalyType.DRIFT:
            parts.append("Temperature exhibited a continuous monotonic calibration drift relative to station baseline")
        else:
            if unusualness > 1.0:
                parts.append(f"LSTM-Autoencoder reconstruction error exceeded station threshold by {unusualness:.1f}x")
            elif any("jump_too_fast" in s for s in sanity_issues):
                parts.append("Temperature experienced an unphysically rapid rate-of-change jump")
            elif any("out_of_bounds" in s for s in sanity_issues):
                parts.append("Reading exceeded hard physical environmental limits")
            elif cross_issues:
                parts.append("Sensor values violated thermodynamic dew point cross-variable constraints")
            else:
                parts.append("Parameter values deviated significantly from expected baseline")

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

        if spatial_issues:
            parts.append("neighboring stations showed no correlated change.")
        elif neighbor_readings:
            parts.append("neighboring stations cross-validated normal regional weather trend.")

        clean_parts = [p.rstrip(".") for p in parts if p]
        text = "; ".join(clean_parts)
        if not text.endswith("."):
            text += "."
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
            valid_neighbors = [
                getattr(n, field)
                for n in neighbor_readings
                if getattr(n, field) is not None and not np.isnan(getattr(n, field))
            ]
            if valid_neighbors:
                val = float(np.median(valid_neighbors))
                corrected[field] = round(val, 1)
            else:
                valid_recent = [
                    getattr(w, field)
                    for w in recent_window
                    if getattr(w, field) is not None and not np.isnan(getattr(w, field))
                ]
                if valid_recent:
                    val = float(np.median(valid_recent[-3:]))
                    corrected[field] = round(val, 1)
                else:
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
    import sys
    sys.path.insert(0, ".")
    from data_loader import load_delhi_12m_history

    print("Loading 12-Month Delhi Station Data...", flush=True)
    station_data = load_delhi_12m_history(force_fetch=False)
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
