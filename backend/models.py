"""
Backend Data Models — Pydantic & Dataclass Definitions
======================================================
Defines input Reading schemas, production contract Alert output shapes,
fault injection requests, and system health status models.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class StationInfo(BaseModel):
    station_id: str
    name: str
    lat: float
    lon: float
    latest_temperature: Optional[float] = None
    latest_pressure: Optional[float] = None
    latest_humidity: Optional[float] = None
    last_updated: Optional[str] = None
    status: str = "ONLINE"


class ReadingModel(BaseModel):
    station_id: str
    timestamp: str
    temperature: Optional[float] = None
    pressure: Optional[float] = None
    humidity: Optional[float] = None
    lat: float
    lon: float
    is_fallback: bool = False


class AlertMessage(BaseModel):
    station_id: str
    timestamp: str
    is_anomaly: bool
    anomaly_type: str
    confidence: float
    reason: str
    corrected_value: Optional[Dict[str, float]] = None


class FaultInjectRequest(BaseModel):
    station_id: str = Field(..., description="Station ID (e.g. igi_airport, red_fort)")
    fault_type: str = Field(..., description="Fault type (spike, dropout, inconsistency, spatial_outlier, frozen, drift)")


class HealthResponse(BaseModel):
    status: str = "HEALTHY"
    polling_active: bool
    total_stations: int
    active_stations: int
    fallback_count: int
    total_alerts: int
    total_polls: int
    model_loaded: bool
    uptime_seconds: float
    timestamp: str
