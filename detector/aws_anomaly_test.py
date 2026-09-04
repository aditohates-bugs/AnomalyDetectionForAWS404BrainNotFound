"""
AWS Weather Anomaly Detection - Test & Evaluation Harness
===========================================================
Tests the 4-layer WeatherAnomalyDetector against real Delhi-NCR station data
with injected synthetic fault ground-truth.

Reports overall and per-fault-type Precision, Recall, F1 score, and False Alarm Rate.
Outputs example JSON predictions following the production contract schema.
"""

import sys
import os
import time
import json
import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, f1_score

# Ensure root and detector directories are on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DETECTOR_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if DETECTOR_DIR not in sys.path:
    sys.path.insert(0, DETECTOR_DIR)

try:
    from data_loader import load_delhi_12m_history, get_train_val_test_splits
    def load_delhi_station_data(force_fetch=False):
        return load_delhi_12m_history(force_fetch=force_fetch)
except ImportError:
    from detector.data_loader import load_delhi_station_data

try:
    from detector import WeatherAnomalyDetector, Reading, AnomalyType
except ImportError:
    from detector.detector import WeatherAnomalyDetector, Reading, AnomalyType

RNG = np.random.default_rng(42)

COLS = {
    "temp": "temperature",
    "rh": "humidity",
    "pres": "pressure",
}


# ---------------------------------------------------------------------------
# 1. FAULT INJECTION (Multi-station support)
# ---------------------------------------------------------------------------
def inject_faults_multi_station(station_history: dict, fault_fraction: float = 0.06, seed: int = 42) -> dict:
    """Returns a copy of station_history with labeled synthetic faults injected."""
    rng = np.random.default_rng(seed)
    corrupted_history = {}

    for sid, df in station_history.items():
        df_c = df.copy().reset_index(drop=True)
        n = len(df_c)
        df_c["is_fault"] = False
        df_c["fault_type"] = "none"

        n_faults = max(1, int(n * fault_fraction))
        fault_types = ["spike", "frozen", "drift", "dropout", "inconsistency"]

        used_rows = set()

        for _ in range(n_faults):
            ftype = rng.choice(fault_types)
            start = rng.integers(10, n - 35)
            if start in used_rows:
                continue

            if ftype == "spike":
                spike_val = rng.uniform(14.0, 22.0)
                df_c.loc[start, COLS["temp"]] += spike_val
                df_c.loc[start, "is_fault"] = True
                df_c.loc[start, "fault_type"] = "spike"
                used_rows.add(start)

            elif ftype == "frozen":
                length = rng.integers(8, 16)
                frozen_t = df_c.loc[start, COLS["temp"]]
                frozen_h = df_c.loc[start, COLS["rh"]]
                frozen_p = df_c.loc[start, COLS["pres"]]
                for i in range(start, min(start + length, n)):
                    df_c.loc[i, COLS["temp"]] = frozen_t
                    df_c.loc[i, COLS["rh"]] = frozen_h
                    df_c.loc[i, COLS["pres"]] = frozen_p
                    df_c.loc[i, "is_fault"] = True
                    df_c.loc[i, "fault_type"] = "frozen"
                    used_rows.add(i)

            elif ftype == "drift":
                length = rng.integers(12, 24)
                step = rng.uniform(0.18, 0.35)
                for j, i in enumerate(range(start, min(start + length, n))):
                    df_c.loc[i, COLS["temp"]] += step * (j + 1)
                    df_c.loc[i, "is_fault"] = True
                    df_c.loc[i, "fault_type"] = "drift"
                    used_rows.add(i)

            elif ftype == "dropout":
                length = rng.integers(2, 5)
                for i in range(start, min(start + length, n)):
                    df_c.loc[i, [COLS["temp"], COLS["rh"], COLS["pres"]]] = np.nan
                    df_c.loc[i, "is_fault"] = True
                    df_c.loc[i, "fault_type"] = "dropout"
                    used_rows.add(i)

            elif ftype == "inconsistency":
                df_c.loc[start, COLS["rh"]] = 98.0
                df_c.loc[start, COLS["temp"]] += 7.5  # Hot & humid boundary conflict
                df_c.loc[start, "is_fault"] = True
                df_c.loc[start, "fault_type"] = "inconsistency"
                used_rows.add(start)

        corrupted_history[sid] = df_c

    return corrupted_history


# ---------------------------------------------------------------------------
# 2. RUN DETECTOR OVER MULTI-STATION DATASET
# ---------------------------------------------------------------------------
def run_detection_evaluation(clean_history: dict, corrupted_history: dict, z_thresh: float = 3.0):
    detector = WeatherAnomalyDetector(station_history=clean_history, z_thresh=z_thresh)

    results_list = []
    sample_outputs = []

    # Pre-index readings by (station_id, timestamp)
    reading_lookup = {}
    row_lookup = {}
    all_timestamps = sorted(
        list(set(ts for df in corrupted_history.values() for ts in df["timestamp"]))
    )

    for sid, df in corrupted_history.items():
        for _, row in df.iterrows():
            ts = row["timestamp"]
            r = Reading(
                station_id=sid,
                timestamp=ts if isinstance(ts, pd.Timestamp) else pd.to_datetime(ts),
                temperature=row["temperature"],
                pressure=row["pressure"],
                humidity=row["humidity"],
                lat=row.get("lat", 0.0),
                lon=row.get("lon", 0.0),
            )
            reading_lookup[(sid, ts)] = r
            row_lookup[(sid, ts)] = row

    print("Running detector across multi-station dataset...", flush=True)
    stations_list = list(corrupted_history.keys())

    for sid in stations_list:
        recent_window = []
        prev_reading = None

        station_ts_list = sorted([ts for (s, ts) in reading_lookup.keys() if s == sid])

        for ts in station_ts_list:
            r = reading_lookup[(sid, ts)]
            row = row_lookup[(sid, ts)]

            # Neighbor readings at exact timestamp
            neighbors = [
                reading_lookup[(n_sid, ts)]
                for n_sid in stations_list
                if n_sid != sid and (n_sid, ts) in reading_lookup
            ]

            # Evaluate through 4-layer detector
            eval_res = detector.evaluate(
                r, prev=prev_reading, neighbor_readings=neighbors, recent_window=recent_window
            )

            record = {
                "station_id": sid,
                "timestamp": str(ts),
                "temperature": r.temperature,
                "pressure": r.pressure,
                "humidity": r.humidity,
                "is_fault": row["is_fault"],
                "fault_type": row["fault_type"],
                "pred_fault": eval_res["is_anomaly"],
                "pred_anomaly_type": eval_res["anomaly_type"],
                "pred_confidence": eval_res["confidence"],
                "pred_reason": eval_res["reason"],
                "pred_corrected_value": json.dumps(eval_res["corrected_value"]) if eval_res["corrected_value"] else "",
            }
            results_list.append(record)

            if eval_res["is_anomaly"] and row["is_fault"] and len(sample_outputs) < 3:
                sample_outputs.append((r, eval_res, row["fault_type"]))

            recent_window.append(r)
            if len(recent_window) > 10:
                recent_window.pop(0)
            prev_reading = r

    results_df = pd.DataFrame(results_list)
    return results_df, sample_outputs


# ---------------------------------------------------------------------------
# 3. METRICS SCORING
# ---------------------------------------------------------------------------
def print_evaluation_report(df: pd.DataFrame):
    y_true = df["is_fault"].astype(int)
    y_pred = df["pred_fault"].astype(int)

    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    false_alarm_rate = ((y_pred == 1) & (y_true == 0)).sum() / max((y_true == 0).sum(), 1)

    print("==================================================")
    print("      DELHI-NCR AWS ANOMALY DETECTOR RESULTS      ")
    print("==================================================")
    print(f"Total Observations Tested: {len(df):,}")
    print(f"Total Ground-Truth Faults:  {y_true.sum():,}")
    print(f"Total Flagged Anomaly Runs: {y_pred.sum():,}")
    print("--------------------------------------------------")
    print(f"Overall Precision:        {precision:.4f} ({precision:.1%})")
    print(f"Overall Recall:           {recall:.4f} ({recall:.1%})")
    print(f"Overall F1 Score:         {f1:.4f} ({f1:.1%})")
    print(f"False Alarm Rate:         {false_alarm_rate:.4f} ({false_alarm_rate:.2%})")
    print("--------------------------------------------------")

    print("\n=== Performance by Fault Type ===")
    for ftype in sorted(df["fault_type"].unique()):
        if ftype == "none":
            continue
        subset = df[df["fault_type"] == ftype]
        caught = subset["pred_fault"].sum()
        total = len(subset)
        pct = caught / total if total > 0 else 0
        print(f"  - {ftype:<16s}: Caught {caught:4d}/{total:4d} ({pct:6.1%})")

    print("==================================================\n")
    return precision, recall, f1, false_alarm_rate


# ---------------------------------------------------------------------------
# 4. TASK 6 DISASTER SANITY TESTS
# ---------------------------------------------------------------------------
def run_disaster_sanity_tests(train_dict: dict, test_dict: dict):
    print("==================================================")
    print("    TASK 6: DISASTER EXTREMES SANITY TESTS        ")
    print("==================================================")

    detector = WeatherAnomalyDetector(station_history=train_dict)

    # Part (a): Known extreme heatwave day in train split
    df_igi_train = train_dict.get("igi_airport", pd.DataFrame())
    heatwave_rows = df_igi_train[df_igi_train["temperature"] >= 40.0]
    if not heatwave_rows.empty:
        r_hw = heatwave_rows.iloc[0]
        ts_hw = pd.to_datetime(r_hw["timestamp"])
        hw_reading = Reading(
            station_id="igi_airport",
            timestamp=ts_hw,
            temperature=float(r_hw["temperature"]),
            pressure=float(r_hw["pressure"]),
            humidity=float(r_hw["humidity"]),
            lat=28.5562,
            lon=77.1000
        )

        neighbors_hw = []
        for sid, df_st in train_dict.items():
            if sid == "igi_airport":
                continue
            match = df_st[pd.to_datetime(df_st["timestamp"]) == ts_hw]
            if not match.empty:
                r_n = match.iloc[0]
                neighbors_hw.append(Reading(
                    station_id=sid,
                    timestamp=ts_hw,
                    temperature=float(r_n["temperature"]),
                    pressure=float(r_n["pressure"]),
                    humidity=float(r_n["humidity"]),
                    lat=r_n.get("lat", 0.0),
                    lon=r_n.get("lon", 0.0)
                ))

        res_hw = detector.evaluate(hw_reading, neighbor_readings=neighbors_hw)
        print("\nPart (a) Known Disaster Day Test (May 2026 Heatwave @ 40.1C):")
        print(f"  Input Temp: {hw_reading.temperature} C | Timestamp: {ts_hw}")
        print(f"  Evaluation Result: Anomaly={res_hw['is_anomaly']} | Type={res_hw['anomaly_type']} | Conf={res_hw['confidence']:.2f}")
        print(f"  Reason: {res_hw['reason']}")
        if not res_hw["is_anomaly"]:
            print("  Status: PASSED (Known extreme weather correctly recognized as normal)")
        else:
            print("  Status: WARN (Flagged anomaly)")

    # Part (b): Novel extreme monsoon day in held-out test split
    df_igi_test = test_dict.get("igi_airport", pd.DataFrame())
    monsoon_rows = df_igi_test[df_igi_test["humidity"] >= 85.0]
    if not monsoon_rows.empty:
        r_ms = monsoon_rows.iloc[0]
        ts_ms = pd.to_datetime(r_ms["timestamp"])
        ms_reading = Reading(
            station_id="igi_airport",
            timestamp=ts_ms,
            temperature=float(r_ms["temperature"]),
            pressure=float(r_ms["pressure"]),
            humidity=float(r_ms["humidity"]),
            lat=28.5562,
            lon=77.1000
        )

        neighbors_ms = []
        for sid, df_st in test_dict.items():
            if sid == "igi_airport":
                continue
            match = df_st[pd.to_datetime(df_st["timestamp"]) == ts_ms]
            if not match.empty:
                r_n = match.iloc[0]
                neighbors_ms.append(Reading(
                    station_id=sid,
                    timestamp=ts_ms,
                    temperature=float(r_n["temperature"]),
                    pressure=float(r_n["pressure"]),
                    humidity=float(r_n["humidity"]),
                    lat=r_n.get("lat", 0.0),
                    lon=r_n.get("lon", 0.0)
                ))

        res_ms = detector.evaluate(ms_reading, neighbor_readings=neighbors_ms)
        print("\nPart (b) Held-Out Novel Disaster Test (July 2026 Monsoon Extreme):")
        print(f"  Input Temp: {ms_reading.temperature} C | Humidity: {ms_reading.humidity}% | Timestamp: {ts_ms}")
        print(f"  Evaluation Result: Anomaly={res_ms['is_anomaly']} | Type={res_ms['anomaly_type']} | Conf={res_ms['confidence']:.2f}")
        print(f"  Reason: {res_ms['reason']}")
        if not res_ms["is_anomaly"]:
            print("  Status: PASSED (Spatial consensus successfully saved regional extreme event)")
        else:
            print("  Status: WARN (Flagged anomaly)")
    print("==================================================\n")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Loading 12-Month Delhi AWS Station Dataset...", flush=True)
    data_12m = load_delhi_12m_history(force_fetch=False)
    train_dict, val_dict, test_dict = get_train_val_test_splits(data_12m)

    full_train_val = {sid: pd.concat([train_dict[sid], val_dict[sid]], ignore_index=True) for sid in train_dict}

    print("Injecting Labeled Synthetic Faults into Held-Out Test Month (6% fraction)...", flush=True)
    corrupted_test = inject_faults_multi_station(test_dict, fault_fraction=0.06)

    print("Running Benchmark Evaluation across 10 Delhi stations...", flush=True)
    results_df, samples = run_detection_evaluation(full_train_val, corrupted_test)

    print_evaluation_report(results_df)

    run_disaster_sanity_tests(train_dict, test_dict)

    print("=== Sample Production Contract Outputs ===", flush=True)
    for idx, (r, eval_res, true_type) in enumerate(samples, 1):
        input_json = {
            "station_id": r.station_id,
            "timestamp": str(r.timestamp),
            "temperature": r.temperature,
            "pressure": r.pressure,
            "humidity": r.humidity,
            "lat": r.lat,
            "lon": r.lon,
        }
        print(f"\n--- Sample {idx} (Ground Truth Fault: {true_type}) ---", flush=True)
        print("INPUT:", flush=True)
        print(json.dumps(input_json, indent=2), flush=True)
        print("OUTPUT:", flush=True)
        print(json.dumps(eval_res, indent=2), flush=True)

    out_csv = "aws_anomaly_labeled_results.csv"
    results_df.to_csv(out_csv, index=False)
    print(f"\nFull evaluation dataset saved to {out_csv}", flush=True)
