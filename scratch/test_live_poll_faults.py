import os
import sys
import asyncio
import pandas as pd

sys.path.insert(0, ".")

from backend.state import app_state
from backend.live_poll_loop import run_live_poll_round

async def test_live_poll_all_faults():
    app_state.initialize()
    
    stations = list(app_state.station_history.keys())
    fault_types = ["spike", "dropout", "inconsistency", "spatial_outlier", "frozen", "drift"]

    for fault_type in fault_types:
        for target_sid in [stations[0], stations[4]]: # e.g. igi_airport, chandni_chowk
            print(f"\n=======================================================")
            print(f" TESTING FAULT INJECTION: '{fault_type}' on '{target_sid}'")
            print(f"=======================================================")
            
            # Queue fault
            app_state.fault_injector.trigger_fault(target_sid, fault_type)

            # Capture broadcast data by overriding broadcast_json
            broadcast_results = {}
            async def fake_broadcast(data):
                nonlocal broadcast_results
                if data.get("event") == "POLL_UPDATE":
                    broadcast_results = data.get("evaluations", {})

            app_state.connection_manager.broadcast_json = fake_broadcast

            # Run 1 live poll round
            await run_live_poll_round()

            # Inspect WebSocket evaluation payloads for all 10 stations
            anomalous_stations = []
            for sid, res in broadcast_results.items():
                if res["is_anomaly"]:
                    anomalous_stations.append((sid, res["anomaly_type"], res["reason"]))

            print(f"Total Anomalous Stations: {len(anomalous_stations)} / 10")
            for sid, atype, rsn in anomalous_stations:
                print(f"   -> {sid:20s}: anomaly_type={atype:15s} | target={sid == target_sid}")
                if sid != target_sid:
                    print(f"      [FALSE POSITIVE DETAILS] reason: {rsn}")

if __name__ == "__main__":
    asyncio.run(test_live_poll_all_faults())
