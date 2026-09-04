import os
import sys
import pandas as pd
import json

sys.path.insert(0, ".")

from detector.detector import WeatherAnomalyDetector, Reading
from data_loader import load_delhi_12m_history

def test_single_fault_isolation():
    station_data = load_delhi_12m_history(force_fetch=False)
    detector = WeatherAnomalyDetector(station_history=station_data)

    stations = list(station_data.keys())
    target_sid = "igi_airport"

    # Build normal readings for all stations at a fixed index
    idx = 500
    readings = {}
    for sid in stations:
        df = station_data[sid]
        readings[sid] = Reading(
            station_id=sid,
            timestamp=df.iloc[idx]["timestamp"],
            temperature=float(df.iloc[idx]["temperature"]),
            pressure=float(df.iloc[idx]["pressure"]),
            humidity=float(df.iloc[idx]["humidity"]),
            lat=float(df.iloc[idx]["lat"]),
            lon=float(df.iloc[idx]["lon"]),
        )

    print(f"Original temperature for {target_sid}: {readings[target_sid].temperature}°C")
    # Inject spike into igi_airport only
    readings[target_sid].temperature += 20.0
    print(f"Corrupted temperature for {target_sid}: {readings[target_sid].temperature}°C")

    # Evaluate all 10 stations
    results = {}
    for sid, r in readings.items():
        neighbors = [n_r for n_sid, n_r in readings.items() if n_sid != sid]
        res = detector.evaluate(r=r, prev=None, neighbor_readings=neighbors, recent_window=[])
        results[sid] = res

    print("\n--- EVALUATION RESULTS FOR ALL STATIONS ---")
    for sid, res in results.items():
        print(f"Station {sid:20s}: is_anomaly={res['is_anomaly']} | anomaly_type={res['anomaly_type']} | reason={res['reason']}")

if __name__ == "__main__":
    test_single_fault_isolation()
