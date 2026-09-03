"""
Live Polling Engine & Replay Fallback Loop for Open-Meteo AWS Weather Data
==========================================================================
Polls Open-Meteo current weather endpoint for all 10 Delhi-NCR AWS stations
at a conservative 5-15 minute cadence (respecting API rate limits).

Features:
  1. Live polling against https://api.open-meteo.com/v1/forecast (no API key required).
  2. Automatic fallback to last known station reading on network/API failure.
  3. Continuous append-only logging to disk (`live_readings_log.csv`).
  4. Manual replay mode switch using local log file when API is unreachable.
  5. Live fault injection hook for live interactive demo triggers.
"""

import os
import sys
import argparse
import asyncio
import json
import urllib.request
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, List, Dict

sys.path.insert(0, ".")
from data_loader import STATIONS, load_delhi_12m_history
from detector.detector import WeatherAnomalyDetector, Reading, AnomalyType

LIVE_LOG_FILE = "live_readings_log.csv"


class FaultInjector:
    def __init__(self):
        self.pending_faults = {}  # {station_id: fault_type}

    def trigger_fault(self, station_id: str, fault_type: str):
        """Trigger synthetic fault injection for next live polling tick."""
        self.pending_faults[station_id] = fault_type
        print(f" [FaultInjector] Queued '{fault_type}' fault for station '{station_id}'.", flush=True)

    def corrupt(self, r: Reading, fault_type: str) -> Reading:
        print(f" [FaultInjector] Injecting '{fault_type}' fault on station '{r.station_id}' reading.", flush=True)
        if fault_type == "spike":
            r.temperature += 18.5
        elif fault_type == "frozen":
            r.temperature = 30.0
            r.humidity = 70.0
            r.pressure = 980.0
        elif fault_type == "dropout":
            r.temperature = np.nan
            r.humidity = np.nan
            r.pressure = np.nan
        elif fault_type == "inconsistency":
            r.temperature = 42.0
            r.humidity = 98.0
        elif fault_type == "spatial_outlier":
            r.temperature += 4.0
        elif fault_type == "drift":
            r.temperature += 3.5
        return r


async def fetch_open_meteo_current(lat: float, lon: float) -> dict:
    """Fetch current temperature, relative humidity, and surface pressure from Open-Meteo."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&"
        f"current=temperature_2m,relative_humidity_2m,surface_pressure&timezone=Asia%2FKolkata"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    req = urllib.request.Request(url, headers=headers)

    loop = asyncio.get_running_loop()
    def _do_fetch():
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return await loop.run_in_executor(None, _do_fetch)


def append_reading_to_log(r: Reading, is_fallback: bool = False):
    """Appends live reading to local append-only disk log."""
    file_exists = os.path.exists(LIVE_LOG_FILE)
    df_row = pd.DataFrame([{
        "timestamp": r.timestamp,
        "station_id": r.station_id,
        "temperature": r.temperature,
        "pressure": r.pressure,
        "humidity": r.humidity,
        "lat": r.lat,
        "lon": r.lon,
        "is_fallback": is_fallback
    }])
    df_row.to_csv(LIVE_LOG_FILE, mode="a", header=not file_exists, index=False)


async def run_live_poll_loop(
    poll_interval_sec: int = 300,
    max_rounds: Optional[int] = None,
    detector: Optional[WeatherAnomalyDetector] = None,
    fault_injector: Optional[FaultInjector] = None
):
    """Main live polling loop across all 10 Delhi-NCR stations."""
    if detector is None:
        station_data = load_delhi_12m_history(force_fetch=False)
        detector = WeatherAnomalyDetector(station_history=station_data)

    if fault_injector is None:
        fault_injector = FaultInjector()

    last_known_reading: Dict[str, Reading] = {}
    last_reading_per_station: Dict[str, Reading] = {}
    recent_window_per_station: Dict[str, List[Reading]] = {}

    round_idx = 0
    print(f"\n[LIVE POLL] Starting Live Open-Meteo Weather Polling Loop ({poll_interval_sec}s interval)...", flush=True)

    while True:
        round_idx += 1
        print(f"\n--- Polling Round {round_idx} [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ---", flush=True)

        for sid, info in STATIONS.items():
            is_fallback = False
            try:
                raw = await fetch_open_meteo_current(info["lat"], info["lon"])
                current = raw.get("current", {})
                r = Reading(
                    station_id=sid,
                    timestamp=pd.to_datetime(current.get("time", datetime.now())),
                    temperature=float(current.get("temperature_2m", 25.0)),
                    pressure=float(current.get("surface_pressure", 1000.0)),
                    humidity=float(current.get("relative_humidity_2m", 60.0)),
                    lat=info["lat"],
                    lon=info["lon"]
                )
                last_known_reading[sid] = r
            except Exception as e:
                print(f" [Warning] Live fetch failed for station '{sid}' ({e}). Attempting fallback...", flush=True)
                r = last_known_reading.get(sid)
                if r is None:
                    print(f"  No fallback reading available yet for '{sid}'. Skipping tick.", flush=True)
                    continue
                is_fallback = True
                r.timestamp = pd.to_datetime(datetime.now())

            # Log to local append-only cache
            append_reading_to_log(r, is_fallback=is_fallback)

            # Fault Injection Check
            if sid in fault_injector.pending_faults:
                ftype = fault_injector.pending_faults.pop(sid)
                r = fault_injector.corrupt(r, ftype)

            prev = last_reading_per_station.get(sid)
            neighbors = [
                last_reading_per_station[other_sid]
                for other_sid in STATIONS
                if other_sid != sid and other_sid in last_reading_per_station
            ]
            window = recent_window_per_station.get(sid, [])

            eval_res = detector.evaluate(r, prev=prev, neighbor_readings=neighbors, recent_window=window)

            last_reading_per_station[sid] = r
            recent_window_per_station.setdefault(sid, []).append(r)
            if len(recent_window_per_station[sid]) > 24:
                recent_window_per_station[sid].pop(0)

            print(
                f"  - Station '{sid:<16s}': Temp={r.temperature if not np.isnan(r.temperature) else 'NaN'}°C | "
                f"Anomaly={eval_res['is_anomaly']} ({eval_res['anomaly_type']}) | Conf={eval_res['confidence']:.2f}",
                flush=True
            )

        if max_rounds is not None and round_idx >= max_rounds:
            print(f"\n Completed {max_rounds} live polling rounds.", flush=True)
            break

        await asyncio.sleep(poll_interval_sec)


async def run_replay_loop(
    csv_file: str = LIVE_LOG_FILE,
    tick_delay_sec: float = 0.5,
    detector: Optional[WeatherAnomalyDetector] = None
):
    """Replay mode using local append-only log as safety net during API outages."""
    if not os.path.exists(csv_file):
        csv_file = "delhi_weather_12m.csv"

    print(f"\n[REPLAY MODE] Reading from local cached dataset ({csv_file})...", flush=True)
    df_all = pd.read_csv(csv_file)
    df_all["timestamp"] = pd.to_datetime(df_all["timestamp"])

    if detector is None:
        station_data = load_delhi_12m_history(force_fetch=False)
        detector = WeatherAnomalyDetector(station_history=station_data)

    last_reading_per_station = {}
    recent_window_per_station = {}

    timestamps = sorted(df_all["timestamp"].unique())
    print(f"[REPLAY MODE] Replaying {len(timestamps)} historical ticks...", flush=True)

    for ts in timestamps[:100]:  # Replay first 100 ticks
        df_ts = df_all[df_all["timestamp"] == ts]

        for _, row in df_ts.iterrows():
            sid = row["station_id"]
            r = Reading(
                station_id=sid,
                timestamp=ts,
                temperature=row["temperature"],
                pressure=row["pressure"],
                humidity=row["humidity"],
                lat=row.get("lat", 0.0),
                lon=row.get("lon", 0.0),
            )

            prev = last_reading_per_station.get(sid)
            neighbors = [
                last_reading_per_station[other_sid]
                for other_sid in last_reading_per_station
                if other_sid != sid
            ]
            window = recent_window_per_station.get(sid, [])

            eval_res = detector.evaluate(r, prev=prev, neighbor_readings=neighbors, recent_window=window)

            last_reading_per_station[sid] = r
            recent_window_per_station.setdefault(sid, []).append(r)
            if len(recent_window_per_station[sid]) > 24:
                recent_window_per_station[sid].pop(0)

        await asyncio.sleep(tick_delay_sec)

    print(" Replay demonstration completed successfully.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delhi AWS Weather Anomaly Live Polling Engine")
    parser.add_argument("--mode", choices=["live", "replay"], default="live", help="Mode: live polling or local replay")
    parser.add_argument("--interval", type=int, default=5, help="Poll interval in seconds (for test run)")
    parser.add_argument("--rounds", type=int, default=2, help="Number of polling rounds to run")
    parser.add_argument("--fault", type=str, default="", help="Fault type to inject (e.g. spike, frozen, dropout)")
    parser.add_argument("--station", type=str, default="igi_airport", help="Station ID for fault injection")

    args = parser.parse_args()

    injector = FaultInjector()
    if args.fault:
        injector.trigger_fault(args.station, args.fault)

    if args.mode == "live":
        asyncio.run(run_live_poll_loop(poll_interval_sec=args.interval, max_rounds=args.rounds, fault_injector=injector))
    else:
        asyncio.run(run_replay_loop(tick_delay_sec=0.2))
