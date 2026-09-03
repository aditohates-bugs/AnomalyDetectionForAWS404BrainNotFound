"""
FastAPI Backend Application — AWS Weather Anomaly Detector (SIH26073)
=======================================================================
Exposes REST and WebSocket APIs for live station monitoring, alert streaming,
synthetic fault injection, and system health status.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.config import STATIONS, POLL_INTERVAL_SEC
from backend.models import HealthResponse, FaultInjectRequest, AlertMessage, StationInfo
from backend.state import app_state
from backend.live_poll_loop import live_poll_background_loop, run_live_poll_round


from backend.history import get_station_history, get_all_stations_history


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize AppState & Detector
    app_state.initialize()
    
    # Run initial polling round immediately on startup
    print(" [FastAPI] Running initial live polling round...", flush=True)
    await run_live_poll_round()

    # Start background polling task
    polling_task = asyncio.create_task(live_poll_background_loop())
    
    yield
    
    # Shutdown: Cancel background polling task
    print(" [FastAPI] Shutting down backend...", flush=True)
    polling_task.cancel()
    await app_state.connection_manager.broadcast_json({"event": "SERVER_SHUTDOWN"})


app = FastAPI(
    title="Delhi AWS Weather Anomaly Detector API",
    description="LSTM-Autoencoder + 4-Layer Corroboration Anomaly Detection Backend",
    version="2.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def get_health():
    """At-a-glance health status endpoint for live rehearsals and monitoring."""
    return HealthResponse(
        status="HEALTHY" if app_state.detector is not None else "INITIALIZING",
        polling_active=app_state.is_polling_active,
        total_stations=len(STATIONS),
        active_stations=len(app_state.latest_readings),
        fallback_count=app_state.fallback_count,
        total_alerts=app_state.total_alerts,
        total_polls=app_state.total_polls,
        model_loaded=app_state.detector is not None and app_state.detector.use_lstm,
        uptime_seconds=round(app_state.get_uptime_seconds(), 2),
        timestamp=datetime.now().isoformat()
    )


@app.get("/stations")
async def get_stations():
    """Returns list of 10 Delhi AWS stations with location and latest weather readings."""
    result = []
    for sid, info in STATIONS.items():
        latest_r = app_state.latest_readings.get(sid)
        result.append({
            "station_id": sid,
            "name": info["name"],
            "lat": info["lat"],
            "lon": info["lon"],
            "temperature": latest_r.temperature if latest_r else None,
            "pressure": latest_r.pressure if latest_r else None,
            "humidity": latest_r.humidity if latest_r else None,
            "last_updated": str(latest_r.timestamp) if latest_r else None,
            "status": "ONLINE" if latest_r else "OFFLINE"
        })
    return {"stations": result}


@app.get("/stations/history")
async def get_all_history(hours: int = 48):
    """Returns last N hours of historical telemetry pre-seeding records for all 10 stations."""
    return {"history": get_all_stations_history(hours=hours)}


@app.get("/stations/{station_id}/history")
async def get_single_station_history(station_id: str, hours: int = 48):
    """Returns last N hours of historical telemetry for a specific station."""
    if station_id not in STATIONS:
        raise HTTPException(status_code=400, detail=f"Unknown station_id '{station_id}'")
    return {
        "station_id": station_id,
        "hours": hours,
        "history": get_station_history(station_id, hours=hours)
    }


@app.post("/inject-fault")
async def inject_fault(req: FaultInjectRequest):
    """
    Queue synthetic fault injection for a station and immediately run a live poll round across all 10 stations.
    Supported fault types: spike, dropout, inconsistency, spatial_outlier, frozen, drift
    """
    if req.station_id not in STATIONS:
        raise HTTPException(status_code=400, detail=f"Unknown station_id '{req.station_id}'. Must be one of {list(STATIONS.keys())}")
    
    valid_faults = ["spike", "dropout", "inconsistency", "spatial_outlier", "frozen", "drift"]
    if req.fault_type.lower() not in valid_faults:
        raise HTTPException(status_code=400, detail=f"Invalid fault_type '{req.fault_type}'. Must be one of {valid_faults}")

    app_state.fault_injector.trigger_fault(req.station_id, req.fault_type)
    
    # Trigger full 10-station polling & evaluation round immediately asynchronously
    asyncio.create_task(run_live_poll_round())
    
    return {
        "status": "EXECUTING_NOW",
        "station_id": req.station_id,
        "fault_type": req.fault_type,
        "message": f"Fault '{req.fault_type}' queued for station '{req.station_id}'. Executing live polling round immediately across all 10 stations."
    }


@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """WebSocket endpoint streaming live station weather updates and anomaly alerts."""
    await app_state.connection_manager.connect(websocket)
    try:
        # Send initial status message on connection
        await websocket.send_json({
            "event": "CONNECTED",
            "message": "Connected to Delhi AWS Weather Anomaly Detector Alert Stream",
            "stations_count": len(STATIONS),
            "timestamp": datetime.now().isoformat()
        })
        
        while True:
            # Keep connection alive & listen for client ping/messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"event": "PONG", "timestamp": datetime.now().isoformat()})
    except WebSocketDisconnect:
        app_state.connection_manager.disconnect(websocket)
    except Exception:
        app_state.connection_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
