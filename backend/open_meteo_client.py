"""
Open-Meteo API Client — Async Weather Fetcher with Fallback
===========================================================
Queries Open-Meteo current-weather endpoint (keyless) for all 10 Delhi AWS stations.
Implements automatic fallback to last known reading on network timeout or failure.
"""

import asyncio
import json
import urllib.request
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, Optional

from detector.detector import Reading
from backend.config import OPEN_METEO_URL, STATIONS


async def fetch_station_current_weather(station_id: str, lat: float, lon: float) -> dict:
    """Fetch current temperature, humidity, and surface pressure for a station."""
    url = (
        f"{OPEN_METEO_URL}?"
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


async def poll_all_stations_current(
    stations: Dict[str, Dict[str, Any]],
    last_known_readings: Optional[Dict[str, Reading]] = None
) -> Dict[str, Reading]:
    """
    Polls all 10 Delhi AWS stations concurrently.
    If fetch succeeds: returns live Reading.
    If fetch fails/times out: falls back to last_known_reading or baseline reading.
    """
    if last_known_readings is None:
        last_known_readings = {}

    readings: Dict[str, Reading] = {}

    async def _fetch_one(sid: str, info: dict):
        try:
            raw = await fetch_station_current_weather(sid, info["lat"], info["lon"])
            curr = raw.get("current", {})
            t = float(curr.get("temperature_2m", 25.0))
            p = float(curr.get("surface_pressure", 1000.0))
            h = float(curr.get("relative_humidity_2m", 60.0))
            
            return Reading(
                station_id=sid,
                timestamp=pd.Timestamp.now(),
                temperature=t,
                pressure=p,
                humidity=h,
                lat=info["lat"],
                lon=info["lon"]
            ), False
        except Exception as e:
            # Fallback to last known reading
            if sid in last_known_readings and last_known_readings[sid] is not None:
                lk = last_known_readings[sid]
                fallback_r = Reading(
                    station_id=sid,
                    timestamp=pd.Timestamp.now(),
                    temperature=lk.temperature,
                    pressure=lk.pressure,
                    humidity=lk.humidity,
                    lat=info["lat"],
                    lon=info["lon"]
                )
            else:
                fallback_r = Reading(
                    station_id=sid,
                    timestamp=pd.Timestamp.now(),
                    temperature=27.0,
                    pressure=982.0,
                    humidity=85.0,
                    lat=info["lat"],
                    lon=info["lon"]
                )
            return fallback_r, True

    tasks = [_fetch_one(sid, info) for sid, info in stations.items()]
    results = await asyncio.gather(*tasks)

    for (r, is_fallback) in results:
        readings[r.station_id] = r

    return readings
