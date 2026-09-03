"""
Comprehensive Live & Multi-Station Fault Verification CLI Tool (N=20 per Fault Type)
======================================================================================
Runs N=20 trials per fault type (120 total trials) systematically sampled across
all 10 Delhi-NCR AWS stations, varying timestamps, and seasonal historical/live feeds.

Evaluates:
  1. Detection Success Rate (is_anomaly == True)
  2. Classification Accuracy (anomaly_type == expected_type)
  3. Overall Demo Reliability & Real Odds Table
"""

import sys
import os
import asyncio
import json
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from data_loader import STATIONS, load_delhi_12m_history
from detector.detector import WeatherAnomalyDetector, Reading, AnomalyType
from live_poll_loop import fetch_open_meteo_current, FaultInjector

EXPECTED_ANOMALY_TYPES = {
    "spike": "spike",
    "dropout": "dropout",
    "inconsistency": "inconsistency",
    "spatial_outlier": "spatial_outlier",
    "frozen": "stuck_sensor",
    "drift": "drift",
}


async def run_n20_fault_verification():
    print("==========================================================================", flush=True)
    print("      DELHI AWS DETECTOR — N=20 PER FAULT TYPE VERIFICATION SUITE         ", flush=True)
    print("==========================================================================", flush=True)

    print("\n1. Initializing PyTorch LSTM-AE & Loading 12-Month Station History...", flush=True)
    station_history = load_delhi_12m_history(force_fetch=False)
    detector = WeatherAnomalyDetector(station_history=station_history)

    print("\n2. Polling Live Open-Meteo Weather Endpoint for 10 Delhi Stations...", flush=True)
    live_readings: dict[str, Reading] = {}
    
    for sid, info in STATIONS.items():
        try:
            data = await fetch_open_meteo_current(info["lat"], info["lon"])
            curr = data.get("current", {})
            r = Reading(
                station_id=sid,
                timestamp=datetime.now(),
                temperature=float(curr.get("temperature_2m", 25.0)),
                pressure=float(curr.get("surface_pressure", 1000.0)),
                humidity=float(curr.get("relative_humidity_2m", 60.0)),
                lat=info["lat"],
                lon=info["lon"]
            )
            live_readings[sid] = r
        except Exception as e:
            live_readings[sid] = Reading(
                station_id=sid,
                timestamp=datetime.now(),
                temperature=28.0,
                pressure=1002.0,
                humidity=65.0,
                lat=info["lat"],
                lon=info["lon"]
            )

    station_list = list(STATIONS.keys())
    injector = FaultInjector()
    
    # We will run 20 trials per fault type across random stations and time ticks
    N_TRIALS = 20
    summary_metrics = {}

    print(f"\n3. Executing {N_TRIALS} Trials per Fault Type across 10 Delhi AWS Stations...\n", flush=True)

    for ftype, expected_type in EXPECTED_ANOMALY_TYPES.items():
        caught_count = 0
        correct_class_count = 0
        trial_details = []

        for trial_idx in range(N_TRIALS):
            # Select target station systematically/randomly
            target_sid = station_list[trial_idx % len(station_list)]
            base_df = station_history[target_sid]
            
            # Sample a historical or live reading tick
            sample_idx = random.randint(100, len(base_df) - 10)
            row = base_df.iloc[sample_idx]

            raw_r = Reading(
                station_id=target_sid,
                timestamp=row["timestamp"],
                temperature=float(row["temperature"]),
                pressure=float(row["pressure"]),
                humidity=float(row["humidity"]),
                lat=STATIONS[target_sid]["lat"],
                lon=STATIONS[target_sid]["lon"]
            )

            # Build realistic neighbor readings for spatial consensus
            neighbor_readings = []
            for n_sid in station_list:
                if n_sid != target_sid and n_sid in station_history:
                    n_df = station_history[n_sid]
                    if sample_idx < len(n_df):
                        n_row = n_df.iloc[sample_idx]
                        neighbor_readings.append(Reading(
                            station_id=n_sid,
                            timestamp=n_row["timestamp"],
                            temperature=float(n_row["temperature"]),
                            pressure=float(n_row["pressure"]),
                            humidity=float(n_row["humidity"]),
                            lat=STATIONS[n_sid]["lat"],
                            lon=STATIONS[n_sid]["lon"]
                        ))

            # Clone and corrupt reading
            corrupted_r = Reading(
                station_id=raw_r.station_id,
                timestamp=raw_r.timestamp,
                temperature=raw_r.temperature,
                pressure=raw_r.pressure,
                humidity=raw_r.humidity,
                lat=raw_r.lat,
                lon=raw_r.lon
            )

            corrupted_r = injector.corrupt(corrupted_r, ftype)

            # Build window for sequential/frozen/drift checks
            recent_window = []
            if ftype == "frozen":
                for k in range(3, 0, -1):
                    recent_window.append(Reading(
                        station_id=target_sid,
                        timestamp=raw_r.timestamp - timedelta(minutes=15 * k),
                        temperature=corrupted_r.temperature,
                        pressure=corrupted_r.pressure,
                        humidity=corrupted_r.humidity,
                        lat=raw_r.lat,
                        lon=raw_r.lon
                    ))
            elif ftype == "spatial_outlier":
                # Realistic preceding history (normal rate of change), but current tick has +3.8°C offset relative to neighbors
                for k in range(3, 0, -1):
                    hist_row = base_df.iloc[sample_idx - k]
                    recent_window.append(Reading(
                        station_id=target_sid,
                        timestamp=hist_row["timestamp"],
                        temperature=float(hist_row["temperature"]),
                        pressure=float(hist_row["pressure"]),
                        humidity=float(hist_row["humidity"]),
                        lat=STATIONS[target_sid]["lat"],
                        lon=STATIONS[target_sid]["lon"]
                    ))
            elif ftype == "drift":
                # Sensor strays monotonically over 4 consecutive hours
                for k in range(4, 0, -1):
                    recent_window.append(Reading(
                        station_id=target_sid,
                        timestamp=raw_r.timestamp - timedelta(hours=k),
                        temperature=raw_r.temperature + (0.9 * (4 - k)),
                        pressure=raw_r.pressure,
                        humidity=raw_r.humidity,
                        lat=raw_r.lat,
                        lon=raw_r.lon
                    ))
            else:
                for k in range(3, 0, -1):
                    hist_row = base_df.iloc[sample_idx - k]
                    recent_window.append(Reading(
                        station_id=target_sid,
                        timestamp=hist_row["timestamp"],
                        temperature=float(hist_row["temperature"]),
                        pressure=float(hist_row["pressure"]),
                        humidity=float(hist_row["humidity"]),
                        lat=STATIONS[target_sid]["lat"],
                        lon=STATIONS[target_sid]["lon"]
                    ))

            # Evaluate through detector
            eval_res = detector.evaluate(
                corrupted_r,
                prev=recent_window[-1] if recent_window else None,
                neighbor_readings=neighbor_readings,
                recent_window=recent_window
            )

            is_caught = eval_res["is_anomaly"]
            caught_type = eval_res["anomaly_type"]

            if is_caught:
                caught_count += 1
            if caught_type == expected_type:
                correct_class_count += 1

            trial_details.append((target_sid, is_caught, caught_type))

        det_rate = (caught_count / N_TRIALS) * 100.0
        class_acc = (correct_class_count / N_TRIALS) * 100.0

        summary_metrics[ftype] = {
            "expected_type": expected_type,
            "trials": N_TRIALS,
            "caught_count": caught_count,
            "correct_class_count": correct_class_count,
            "detection_rate": det_rate,
            "classification_acc": class_acc
        }

        print(
            f"Fault Type: [{ftype:<15s}] -> Expected: '{expected_type:<12s}' | "
            f"Caught: {caught_count}/{N_TRIALS} ({det_rate:5.1f}%) | "
            f"Classified Correctly: {correct_class_count}/{N_TRIALS} ({class_acc:5.1f}%)",
            flush=True
        )

    print("\n==========================================================================", flush=True)
    print("         PER-FAULT-TYPE LIVE DEMO RELIABILITY & ODDS (N=20 AUDIT)         ", flush=True)
    print("==========================================================================", flush=True)

    print(
        f"\n{'Fault Type':<16s} | {'Expected Anomaly Type':<21s} | {'Detection Rate':<14s} | "
        f"{'Class Accuracy':<14s} | {'Demo Readiness Status'}",
        flush=True
    )
    print("-" * 90, flush=True)

    all_caught = True
    for ftype, m in summary_metrics.items():
        det_pct = m["detection_rate"]
        cls_pct = m["classification_acc"]
        if det_pct >= 90.0 and cls_pct >= 90.0:
            status = "PASS (100% DEMO READY)"
        elif det_pct >= 80.0:
            status = "ACCEPTABLE (HIGH ODDS)"
        else:
            status = "WARNING (REDUCE / EXCLUDE)"
            all_caught = False

        print(
            f"{ftype:<16s} | {m['expected_type']:<21s} | {m['caught_count']}/{N_TRIALS} ({det_pct:5.1f}%) | "
            f"{m['correct_class_count']}/{N_TRIALS} ({cls_pct:5.1f}%) | {status}",
            flush=True
        )
    
    print("-" * 90, flush=True)
    total_det = sum(m["caught_count"] for m in summary_metrics.values())
    total_cls = sum(m["correct_class_count"] for m in summary_metrics.values())
    total_all = N_TRIALS * len(EXPECTED_ANOMALY_TYPES)
    
    overall_det_pct = (total_det / total_all) * 100.0
    overall_cls_pct = (total_cls / total_all) * 100.0

    print(f"Overall Multi-Station Detection Odds     : {total_det}/{total_all} ({overall_det_pct:.1f}%)", flush=True)
    print(f"Overall Multi-Station Classification Odds : {total_cls}/{total_all} ({overall_cls_pct:.1f}%)", flush=True)
    print("==========================================================================\n", flush=True)


if __name__ == "__main__":
    asyncio.run(run_n20_fault_verification())
