"""
Data Loader for Delhi-NCR AWS Stations
=======================================
Fetches real historical hourly weather data (temperature, pressure, humidity)
for 10 pilot AWS stations in Delhi-NCR from Open-Meteo and formats it
for detector climatology baseline building & evaluation.
"""

import os
import json
import urllib.request
import pandas as pd
import numpy as np

STATIONS = {
    "igi_airport": {"name": "IGI Airport", "lat": 28.5562, "lon": 77.1000},
    "lodhi_road": {"name": "Lodhi Road", "lat": 28.5913, "lon": 77.2273},
    "red_fort": {"name": "Red Fort", "lat": 28.6562, "lon": 77.2410},
    "qutab_minar": {"name": "Qutab Minar", "lat": 28.5245, "lon": 77.1855},
    "chandni_chowk": {"name": "Chandni Chowk", "lat": 28.6506, "lon": 77.2303},
    "akshardham": {"name": "Akshardham", "lat": 28.6127, "lon": 77.2773},
    "lotus_temple": {"name": "Lotus Temple", "lat": 28.5535, "lon": 77.2588},
    "delhi_university": {"name": "Delhi University", "lat": 28.6892, "lon": 77.2106},
    "ndls": {"name": "New Delhi Railway Station", "lat": 28.6430, "lon": 77.2194},
    "pragati_maidan": {"name": "Pragati Maidan", "lat": 28.6180, "lon": 77.2460},
}

CSV_FILE = "delhi_weather_12m.csv"
PKL_FILE = "delhi_weather_12m.pkl"


def fetch_station_data(station_id: str, lat: float, lon: float, start_date: str = "2026-07-20", end_date: str = "2026-08-25") -> pd.DataFrame:
    """Fetch hourly temperature, humidity, and surface pressure from Open-Meteo."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}&"
        f"start_date={start_date}&end_date={end_date}&"
        f"hourly=temperature_2m,relative_humidity_2m,surface_pressure&timezone=Asia%2FKolkata"
    )
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            hourly = data.get("hourly", {})
            
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(hourly.get("time", [])),
                "temperature": hourly.get("temperature_2m", []),
                "humidity": hourly.get("relative_humidity_2m", []),
                "pressure": hourly.get("surface_pressure", []),
            })
            df["station_id"] = station_id
            df["lat"] = lat
            df["lon"] = lon
            return df
    except Exception as e:
        print(f"[Warning] Failed to fetch data for {station_id}: {e}")
        return pd.DataFrame()


def load_delhi_station_data(force_fetch: bool = False, start_date: str = "2026-07-20", end_date: str = "2026-08-25") -> dict:
    """
    Returns station_history dict: {station_id: DataFrame[timestamp, temperature, pressure, humidity, lat, lon]}
    Reads from local CSV/PKL cache if present unless force_fetch is True.
    """
    if not force_fetch and os.path.exists(PKL_FILE):
        print(f"Loading cached station data from {PKL_FILE}...")
        try:
            return pd.read_pickle(PKL_FILE)
        except Exception:
            pass

    if not force_fetch and os.path.exists(CSV_FILE):
        print(f"Loading cached station data from {CSV_FILE}...")
        df_all = pd.read_csv(CSV_FILE)
        df_all["timestamp"] = pd.to_datetime(df_all["timestamp"])
        station_history = {}
        for sid, group in df_all.groupby("station_id"):
            station_history[sid] = group.reset_index(drop=True)
        return station_history

    print(f"Fetching real historical data for 10 Delhi AWS stations ({start_date} to {end_date})...", flush=True)
    station_history = {}
    all_dfs = []

    for sid, info in STATIONS.items():
        print(f"  - Fetching {info['name']} ({sid})...", flush=True)
        df_st = fetch_station_data(sid, info["lat"], info["lon"], start_date, end_date)
        if not df_st.empty:
            station_history[sid] = df_st
            all_dfs.append(df_st)

    if all_dfs:
        full_df = pd.concat(all_dfs, ignore_index=True)
        full_df.to_csv(CSV_FILE, index=False)
        pd.to_pickle(station_history, PKL_FILE)
        print(f"Successfully cached dataset ({len(full_df)} total records) to {CSV_FILE} and {PKL_FILE}.", flush=True)

    return station_history


def load_delhi_12m_history(force_fetch: bool = False, start_date: str = "2025-08-01", end_date: str = "2026-08-31") -> dict:
    """Alias for 12-month station data loading."""
    try:
        from data_loader import load_delhi_12m_history as root_load
        if root_load != load_delhi_12m_history:
            return root_load(force_fetch=force_fetch, start_date=start_date, end_date=end_date)
    except Exception:
        pass
    return load_delhi_station_data(force_fetch=force_fetch, start_date=start_date, end_date=end_date)


if __name__ == "__main__":
    data = load_delhi_station_data(force_fetch=True)
    print(f"\nLoaded {len(data)} stations:", flush=True)
    for sid, df in data.items():
        print(f"  Station '{sid}': {len(df)} rows, temp range: [{df['temperature'].min():.1f}C, {df['temperature'].max():.1f}C]", flush=True)
