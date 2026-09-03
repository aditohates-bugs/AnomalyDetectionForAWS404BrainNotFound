"""
Historical Telemetry Loader & Query Module
===========================================
Serves 24-48 hour historical telemetry windows from app_state.station_history
for pre-seeding dashboard charts instantly without duplicate disk I/O.
"""

import pandas as pd
from typing import Dict, List, Any
from backend.config import STATIONS
from backend.state import app_state


def get_station_history(station_id: str, hours: int = 48) -> List[Dict[str, Any]]:
    """Returns the last N hours of historical records for a given station."""
    st_df = app_state.station_history.get(station_id)
    if st_df is None or st_df.empty:
        return []
    
    # Take last N hours of records
    tail_df = st_df.tail(hours)
    records = []
    for _, row in tail_df.iterrows():
        ts_val = row["timestamp"]
        ts_str = ts_val.isoformat() if hasattr(ts_val, "isoformat") else str(ts_val)
        records.append({
            "station_id": station_id,
            "timestamp": ts_str,
            "temperature": float(row["temperature"]) if pd.notnull(row["temperature"]) else None,
            "humidity": float(row["humidity"]) if pd.notnull(row["humidity"]) else None,
            "pressure": float(row["pressure"]) if pd.notnull(row["pressure"]) else None,
        })
    return records


def get_all_stations_history(hours: int = 48) -> Dict[str, List[Dict[str, Any]]]:
    """Returns the last N hours of historical records for all 10 stations."""
    result = {}
    for sid in STATIONS.keys():
        result[sid] = get_station_history(sid, hours=hours)
    return result

