"""
Data Loader & Audit for Delhi-NCR AWS Stations (12-Month Dataset)
===================================================================
Fetches 12+ months of contiguous historical hourly weather data for 10 Delhi AWS stations
from Open-Meteo Archive API. Builds time-based splits (Train/Val/Test) and identifies
historical extreme weather windows for oversampling.
"""

import os
import json
import urllib.request
import pandas as pd
import numpy as np
from typing import Dict, Tuple, List

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

CSV_12M_FILE = "delhi_weather_12m.csv"
PKL_12M_FILE = "delhi_weather_12m.pkl"


def fetch_station_12m(station_id: str, lat: float, lon: float, start_date: str = "2025-08-01", end_date: str = "2026-08-31") -> pd.DataFrame:
    """Fetch hourly temperature, humidity, and surface pressure for 12 months."""
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
            
            # Forward-fill / linear interpolate tiny missing gaps if any
            df["temperature"] = df["temperature"].interpolate(method="linear").ffill().bfill()
            df["humidity"] = df["humidity"].interpolate(method="linear").ffill().bfill()
            df["pressure"] = df["pressure"].interpolate(method="linear").ffill().bfill()
            
            return df
    except Exception as e:
        print(f"[Warning] Failed to fetch 12m data for {station_id}: {e}", flush=True)
        return pd.DataFrame()


def load_delhi_12m_history(force_fetch: bool = False, start_date: str = "2025-08-01", end_date: str = "2026-08-31") -> Dict[str, pd.DataFrame]:
    """
    Returns dict of DataFrames: {station_id: DataFrame[timestamp, temperature, pressure, humidity, lat, lon]}
    Reads from local PKL/CSV cache if present.
    """
    if not force_fetch and os.path.exists(PKL_12M_FILE):
        print(f"Loading cached 12-month station data from {PKL_12M_FILE}...", flush=True)
        try:
            return pd.read_pickle(PKL_12M_FILE)
        except Exception:
            pass

    if not force_fetch and os.path.exists(CSV_12M_FILE):
        print(f"Loading cached 12-month station data from {CSV_12M_FILE}...", flush=True)
        df_all = pd.read_csv(CSV_12M_FILE)
        df_all["timestamp"] = pd.to_datetime(df_all["timestamp"])
        station_history = {}
        for sid, group in df_all.groupby("station_id"):
            station_history[sid] = group.reset_index(drop=True)
        return station_history

    print(f"Fetching 12+ months historical hourly data for 10 Delhi AWS stations ({start_date} to {end_date})...", flush=True)
    station_history = {}
    all_dfs = []

    for sid, info in STATIONS.items():
        print(f"  - Fetching {info['name']} ({sid})...", flush=True)
        df_st = fetch_station_12m(sid, info["lat"], info["lon"], start_date, end_date)
        if not df_st.empty:
            station_history[sid] = df_st
            all_dfs.append(df_st)

    if all_dfs:
        full_df = pd.concat(all_dfs, ignore_index=True)
        full_df.to_csv(CSV_12M_FILE, index=False)
        pd.to_pickle(station_history, PKL_12M_FILE)
        print(f"Successfully cached 12-month dataset ({len(full_df)} total records) to {CSV_12M_FILE} and {PKL_12M_FILE}.", flush=True)

    return station_history


def audit_dataset(station_history: Dict[str, pd.DataFrame]) -> dict:
    """Performs data audit to verify seasonality, contiguous timestamps, and extreme weather events."""
    audit_results = {}
    print("\n==================================================", flush=True)
    print("        DELHI-NCR 12-MONTH DATA AUDIT REPORT       ", flush=True)
    print("==================================================", flush=True)
    
    total_obs = sum(len(df) for df in station_history.values())
    print(f"Total Stations: {len(station_history)}")
    print(f"Total Observations Across All Stations: {total_obs:,}")

    first_df = next(iter(station_history.values()))
    min_ts = first_df["timestamp"].min()
    max_ts = first_df["timestamp"].max()
    date_range_days = (max_ts - min_ts).days
    months_span = date_range_days / 30.4375

    print(f"Date Span: {min_ts.strftime('%Y-%m-%d')} to {max_ts.strftime('%Y-%m-%d')} ({date_range_days} days / {months_span:.1f} months)")
    print("--------------------------------------------------", flush=True)

    # Check Season Representation
    months_present = set()
    for df in station_history.values():
        months_present.update(df["timestamp"].dt.month.unique())
    
    seasons = {
        "Monsoon (Jul-Sep)": bool(months_present.intersection({7, 8, 9})),
        "Post-Monsoon (Oct-Nov)": bool(months_present.intersection({10, 11})),
        "Winter (Dec-Feb)": bool(months_present.intersection({12, 1, 2})),
        "Summer Heatwaves (Mar-Jun)": bool(months_present.intersection({3, 4, 5, 6})),
    }
    
    print("Seasonality Audit:")
    for s_name, is_rep in seasons.items():
        status = "PASSED" if is_rep else "MISSING"
        print(f"  - {s_name:<30s}: {status}")

    # Detect Extreme Disaster Windows for Oversampling
    disaster_windows = []
    for sid, df in station_history.items():
        # Extreme Heatwave: Temp > 40.0°C
        heat_rows = df[df["temperature"] >= 40.0]
        # Monsoon Cloudburst: RH > 95% & Temp > 32°C
        cloudburst_rows = df[(df["humidity"] >= 95.0) & (df["temperature"] >= 32.0)]
        # Winter Cold Wave: Temp < 7.0°C
        cold_rows = df[df["temperature"] <= 7.0]

        disaster_windows.append({
            "station_id": sid,
            "heatwave_hours": len(heat_rows),
            "cloudburst_hours": len(cloudburst_rows),
            "coldwave_hours": len(cold_rows),
        })

    disaster_df = pd.DataFrame(disaster_windows)
    print("\nHistorical Extreme Weather Event Counts per Station:")
    print(f"  - Total Heatwave Hours (Temp >= 40°C): {disaster_df['heatwave_hours'].sum():,}")
    print(f"  - Total Monsoon Extreme Hours (RH>=95% & Temp>=32°C): {disaster_df['cloudburst_hours'].sum():,}")
    print(f"  - Total Winter Coldwave Hours (Temp <= 7°C): {disaster_df['coldwave_hours'].sum():,}")
    print("==================================================\n", flush=True)

    audit_results = {
        "total_stations": len(station_history),
        "total_observations": total_obs,
        "days_span": date_range_days,
        "months_span": months_span,
        "seasons": seasons,
        "audit_pass": len(months_present) >= 12 and date_range_days >= 350,
    }
    return audit_results


def impute_missing_values(df: pd.DataFrame, method: str = "spline") -> pd.DataFrame:
    """
    Handle transmission dropouts with spline interpolation or forward-fill.
    """
    from scipy.interpolate import interp1d
    
    df = df.copy()
    for col in ["temperature", "pressure", "humidity"]:
        if col not in df.columns:
            continue
        
        valid_mask = df[col].notna()
        if valid_mask.sum() < 2:
            df[col] = df[col].fillna(df[col].mean() if df[col].mean() > 0 else 20.0)
            continue
        
        valid_indices = np.where(valid_mask)[0]
        valid_values = df[col].values[valid_indices]
        
        if method == "spline":
            try:
                f = interp1d(valid_indices, valid_values, kind='cubic', fill_value='extrapolate', bounds_error=False)
                df[col] = f(np.arange(len(df)))
            except Exception:
                df[col] = df[col].interpolate(method='linear', limit_direction='both')
        elif method == "linear":
            df[col] = df[col].interpolate(method='linear', limit_direction='both')
        elif method == "ffill":
            df[col] = df[col].ffill().bfill()
    
    return df


def add_sensor_noise(df: pd.DataFrame, noise_std: float = 0.2, quantization: float = 0.1) -> pd.DataFrame:
    """
    Add stochastic sensor noise + quantization to simulate real hardware.
    """
    df = df.copy()
    rng = np.random.default_rng(42)
    
    for col, sigma in [("temperature", noise_std), ("pressure", noise_std * 1.5), ("humidity", noise_std * 0.5)]:
        if col not in df.columns:
            continue
        
        noise = rng.normal(0, sigma, len(df))
        df[col] = df[col] + noise
        df[col] = np.round(df[col] / quantization) * quantization
        
        spike_mask = rng.random(len(df)) < 0.001
        spike_magnitude = rng.uniform(-5, 5, len(df))
        df.loc[spike_mask, col] = df.loc[spike_mask, col] + spike_magnitude[spike_mask]
    
    return df


def compute_data_quality_report(station_history: dict) -> pd.DataFrame:
    """Compute completeness, range, and anomaly metrics per station."""
    quality_metrics = []
    for sid, df in station_history.items():
        metrics = {
            "station_id": sid,
            "total_records": len(df),
            "date_range": f"{df['timestamp'].min().date()} to {df['timestamp'].max().date()}",
            "temp_completeness_%": (df["temperature"].notna().sum() / len(df)) * 100,
            "humidity_completeness_%": (df["humidity"].notna().sum() / len(df)) * 100,
            "pressure_completeness_%": (df["pressure"].notna().sum() / len(df)) * 100,
            "temp_range_C": f"[{df['temperature'].min():.1f}, {df['temperature'].max():.1f}]",
            "humidity_range_%": f"[{df['humidity'].min():.1f}, {df['humidity'].max():.1f}]",
            "pressure_range_hPa": f"[{df['pressure'].min():.1f}, {df['pressure'].max():.1f}]",
        }
        quality_metrics.append(metrics)
    return pd.DataFrame(quality_metrics)


def detect_extreme_windows(station_history: dict, temp_threshold: float = 40.0) -> dict:
    """Identify extreme weather windows (heatwaves, cold snaps, monsoons)."""
    extreme_windows = {}
    for sid, df in station_history.items():
        extreme_windows[sid] = {
            "heatwave": int((df["temperature"] >= temp_threshold).sum()),
            "cold_snap": int((df["temperature"] <= 7.0).sum()),
            "high_humidity": int((df["humidity"] >= 85.0).sum()),
            "low_humidity": int((df["humidity"] <= 10.0).sum()),
            "extreme_pressure": int(((df["pressure"] < 950.0) | (df["pressure"] > 1030.0)).sum()),
        }
    return extreme_windows


def compute_station_distances() -> np.ndarray:
    """Compute pairwise distances (km) between all 10 stations."""
    from math import radians, cos, sin, asin, sqrt
    
    def haversine(lat1, lon1, lat2, lon2):
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        return 2 * asin(sqrt(a)) * 6371
    
    n = len(STATIONS)
    dist_matrix = np.zeros((n, n))
    sids = list(STATIONS.keys())
    for i in range(n):
        for j in range(i + 1, n):
            s1, s2 = STATIONS[sids[i]], STATIONS[sids[j]]
            d = haversine(s1["lat"], s1["lon"], s2["lat"], s2["lon"])
            dist_matrix[i][j] = d
            dist_matrix[j][i] = d
    return dist_matrix


def get_train_val_test_splits(
    station_history: Dict[str, pd.DataFrame],
    train_frac: float = 0.6,
    val_frac: float = 0.2
) -> Tuple[dict, dict, dict]:
    """
    Time-based split without data leakage:
    - Train: First train_frac (default 60%)
    - Val:   Next val_frac (default 20%)
    - Test:  Remaining portion (default 20%)
    """
    train_dict, val_dict, test_dict = {}, {}, {}

    for sid, df in station_history.items():
        df_sorted = df.sort_values("timestamp").reset_index(drop=True)
        n = len(df_sorted)
        
        n_train = int(n * train_frac)
        n_val = int(n * (train_frac + val_frac))

        train_dict[sid] = df_sorted.iloc[:n_train].reset_index(drop=True)
        val_dict[sid] = df_sorted.iloc[n_train:n_val].reset_index(drop=True)
        test_dict[sid] = df_sorted.iloc[n_val:].reset_index(drop=True)

    return train_dict, val_dict, test_dict


if __name__ == "__main__":
    data_12m = load_delhi_12m_history(force_fetch=False)
    audit_info = audit_dataset(data_12m)
    train_s, val_s, test_s = get_train_val_test_splits(data_12m)
    
    first_sid = next(iter(train_s.keys()))
    print(f"Time-Based Splits for '{first_sid}':")
    print(f"  - Train Split: {len(train_s[first_sid])} rows ({train_s[first_sid]['timestamp'].min().strftime('%Y-%m-%d')} to {train_s[first_sid]['timestamp'].max().strftime('%Y-%m-%d')})")
    print(f"  - Val Split:   {len(val_s[first_sid])} rows ({val_s[first_sid]['timestamp'].min().strftime('%Y-%m-%d')} to {val_s[first_sid]['timestamp'].max().strftime('%Y-%m-%d')})")
    print(f"  - Test Split:  {len(test_s[first_sid])} rows ({test_s[first_sid]['timestamp'].min().strftime('%Y-%m-%d')} to {test_s[first_sid]['timestamp'].max().strftime('%Y-%m-%d')})")
