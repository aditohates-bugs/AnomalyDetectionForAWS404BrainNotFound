"""
Backend Configuration — Delhi-NCR AWS Weather Anomaly Detector
================================================================
Defines 10 Delhi-NCR AWS stations, Open-Meteo API settings, polling intervals,
log paths, and server configuration.
"""

import os
from typing import Dict, Any

STATIONS: Dict[str, Dict[str, Any]] = {
    "igi_airport": {"name": "IGI Airport (Palam)", "lat": 28.5562, "lon": 77.1000},
    "lodhi_road": {"name": "Lodhi Road IMD", "lat": 28.5918, "lon": 77.2273},
    "red_fort": {"name": "Red Fort (Old Delhi)", "lat": 28.6562, "lon": 77.2410},
    "qutab_minar": {"name": "Qutab Minar (Mehrauli)", "lat": 28.5245, "lon": 77.1855},
    "chandni_chowk": {"name": "Chandni Chowk", "lat": 28.6506, "lon": 77.2303},
    "akshardham": {"name": "Akshardham (East Delhi)", "lat": 28.6127, "lon": 77.2773},
    "lotus_temple": {"name": "Lotus Temple (Kalkaji)", "lat": 28.5535, "lon": 77.2588},
    "delhi_university": {"name": "Delhi University (North Campus)", "lat": 28.6904, "lon": 77.2066},
    "ndls": {"name": "New Delhi Railway Station", "lat": 28.6430, "lon": 77.2194},
    "pragati_maidan": {"name": "Pragati Maidan", "lat": 28.6172, "lon": 77.2485},
}

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "300"))  # 5 min polling cadence
LIVE_LOG_FILE = os.getenv("LIVE_LOG_FILE", "live_readings_log.csv")
MODEL_PATH = "detector/lstm_ae_model.pth"
CONFIG_PATH = "detector/lstm_ae_config.pkl"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
