"""
Application State Singleton — Shared Detector & Polling Memory
===============================================================
Maintains in-memory state, history buffers, detector instances, fault injectors,
and system health metrics for the backend.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Any

from detector.detector import WeatherAnomalyDetector, Reading
from data_loader import load_delhi_12m_history, STATIONS
from backend.fault_injector import FaultInjector
from backend.connection_manager import ConnectionManager
from backend.config import MODEL_PATH, CONFIG_PATH, LIVE_LOG_FILE


class AppState:
    def __init__(self):
        self.detector: Optional[WeatherAnomalyDetector] = None
        self.station_history: Dict[str, pd.DataFrame] = {}
        self.latest_readings: Dict[str, Reading] = {}
        self.recent_windows: Dict[str, List[Reading]] = {sid: [] for sid in STATIONS}
        self.last_known_readings: Dict[str, Reading] = {}
        self.fault_injector = FaultInjector()
        self.connection_manager = ConnectionManager()
        
        # Performance & Health Stats
        self.start_time = time.time()
        self.total_polls = 0
        self.active_stations_count = len(STATIONS)
        self.fallback_count = 0
        self.total_alerts = 0
        self.last_poll_time: Optional[str] = None
        self.is_polling_active = False

    def initialize(self):
        """Load 12-month Delhi station history and PyTorch LSTM-AE detector."""
        print(" [AppState] Loading 12-Month Delhi Station History...", flush=True)
        self.station_history = load_delhi_12m_history(force_fetch=False)
        
        print(" [AppState] Initializing WeatherAnomalyDetector & PyTorch LSTM-AE...", flush=True)
        self.detector = WeatherAnomalyDetector(
            station_history=self.station_history,
            model_path=MODEL_PATH,
            config_path=CONFIG_PATH
        )
        print(" [AppState] Core initialization complete.", flush=True)

    def update_reading(self, r: Reading, is_fallback: bool = False):
        self.latest_readings[r.station_id] = r
        if not is_fallback:
            self.last_known_readings[r.station_id] = r
        else:
            self.fallback_count += 1
            
        # Update rolling window (keep up to 24 readings)
        w = self.recent_windows.get(r.station_id, [])
        w.append(r)
        if len(w) > 24:
            w.pop(0)
        self.recent_windows[r.station_id] = w

    def get_uptime_seconds(self) -> float:
        return time.time() - self.start_time


app_state = AppState()
