import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, ".")

from detector.detector import WeatherAnomalyDetector, Reading
from data_loader import load_delhi_12m_history

def test_hypothesis1():
    station_data = load_delhi_12m_history(force_fetch=False)
    detector = WeatherAnomalyDetector(station_history=station_data)

    stations = list(station_data.keys())
    target_sid = "igi_airport"

    # Suppose all stations have normal temp ~ 25°C
    readings = {}
    for sid in stations:
        readings[sid] = Reading(
            station_id=sid,
            timestamp=pd.Timestamp.now(),
            temperature=25.0,
            pressure=1000.0,
            humidity=60.0
        )

    # Ingest a severe fault in igi_airport: e.g. spike (+18.5 -> 43.5°C)
    readings[target_sid].temperature = 43.5

    print(f"\nTarget station '{target_sid}' temp set to {readings[target_sid].temperature}°C (Spike).")
    print(f"Other 9 stations temp set to 25.0°C (Normal).\n")

    for sid, r in readings.items():
        neighbors = [n_r for n_sid, n_r in readings.items() if n_sid != sid]
        
        # Log neighbor statistics calculated inside check_spatial for temperature
        vals = np.array([n.temperature for n in neighbors if n.temperature is not None])
        n_mean = vals.mean()
        n_std = vals.std()
        n_median = float(np.median(vals))
        q75, q25 = np.percentile(vals, [75 ,25])
        iqr = q75 - q25

        spatial_issues = detector.check_spatial(r, neighbors)
        eval_res = detector.evaluate(r, prev=None, neighbor_readings=neighbors, recent_window=[])

        print(f"Station {sid:20s}: temp={r.temperature:4.1f} | n_mean={n_mean:5.2f}, n_std={n_std:5.2f} | n_median={n_median:4.1f}, iqr={iqr:4.1f} | spatial_issues={spatial_issues} | is_anomaly={eval_res['is_anomaly']}")

if __name__ == "__main__":
    test_hypothesis1()
