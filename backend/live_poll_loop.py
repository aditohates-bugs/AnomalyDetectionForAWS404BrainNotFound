"""
Live Polling Engine — Background Task & Broadcast Loop
======================================================
Polls Open-Meteo current-weather endpoint for all 10 Delhi AWS stations per round.
Applies queued synthetic fault injections, logs readings to disk, evaluates through
PyTorch LSTM-AE + 4-layer detector, and streams results over WebSockets.
"""

import asyncio
import os
import pandas as pd
import numpy as np
from datetime import datetime

from detector.detector import Reading
from backend.config import STATIONS, POLL_INTERVAL_SEC, LIVE_LOG_FILE
from backend.open_meteo_client import poll_all_stations_current
from backend.state import app_state


def append_to_live_log(r: Reading, is_fallback: bool = False):
    """Appends live reading to local append-only CSV log."""
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


async def run_live_poll_round():
    """Executes a single live polling round across all 10 stations."""
    app_state.total_polls += 1
    app_state.last_poll_time = datetime.now().isoformat()
    
    # 1. Fetch ALL 10 stations FIRST before evaluating any (same-tick neighbor comparison)
    readings = await poll_all_stations_current(
        stations=STATIONS,
        last_known_readings=app_state.last_known_readings
    )

    # 2. Check and apply pending fault injections
    eval_readings = {}
    for sid, r in readings.items():
        # Append clean reading to disk log and state memory
        append_to_live_log(r, is_fallback=getattr(r, "is_fallback", False))
        app_state.update_reading(r)

        pending_fault = app_state.fault_injector.get_pending_fault(sid)
        if pending_fault:
            print(f" [LiveLoop] Applying queued '{pending_fault}' fault for station '{sid}'.", flush=True)
            # Create a copy so corruption applies only to this evaluation tick
            corrupted_r = Reading(
                station_id=r.station_id,
                timestamp=r.timestamp,
                temperature=r.temperature,
                pressure=r.pressure,
                humidity=r.humidity,
                lat=r.lat,
                lon=r.lon
            )
            corrupted_r = app_state.fault_injector.corrupt(corrupted_r, pending_fault)
            app_state.fault_injector.clear_fault(sid)
            eval_readings[sid] = corrupted_r
        else:
            eval_readings[sid] = r

    readings = eval_readings

    # 3. Evaluate each station through 4-layer detector
    eval_results = {}
    for sid, r in readings.items():
        neighbors = [n_r for n_sid, n_r in readings.items() if n_sid != sid]
        recent_win = app_state.recent_windows.get(sid, [])
        prev_r = recent_win[-2] if len(recent_win) >= 2 else None

        res = app_state.detector.evaluate(
            r=r,
            prev=prev_r,
            neighbor_readings=neighbors,
            recent_window=recent_win
        )
        eval_results[sid] = res
        
        if res["is_anomaly"]:
            app_state.total_alerts += 1

    # 4. Broadcast live poll update to all connected WebSocket clients
    broadcast_data = {
        "event": "POLL_UPDATE",
        "timestamp": app_state.last_poll_time,
        "readings": {
            sid: {
                "station_id": sid,
                "temperature": r.temperature,
                "pressure": r.pressure,
                "humidity": r.humidity,
                "timestamp": str(r.timestamp)
            } for sid, r in readings.items()
        },
        "evaluations": eval_results
    }
    
    await app_state.connection_manager.broadcast_json(broadcast_data)


async def live_poll_background_loop():
    """Long-running background task that executes live polling rounds every POLL_INTERVAL_SEC."""
    app_state.is_polling_active = True
    print(" [LiveLoop] Starting background polling task...", flush=True)
    
    try:
        while app_state.is_polling_active:
            await run_live_poll_round()
            await asyncio.sleep(POLL_INTERVAL_SEC)
    except asyncio.CancelledError:
        print(" [LiveLoop] Polling task cancelled.", flush=True)
    except Exception as e:
        print(f" [LiveLoop] Error in background polling loop: {e}", flush=True)
    finally:
        app_state.is_polling_active = False
