import React, { useState, useEffect } from 'react';
import { Thermometer, Gauge, Droplets, AlertOctagon, CheckCircle, Database } from 'lucide-react';

export default function StationGrid({ stations, latestEvaluations, selectedStationId, onSelectStation, wsPulseKey }) {
  const [flashingStations, setFlashingStations] = useState({});

  // Flash station cards briefly when a live WebSocket poll update arrives
  useEffect(() => {
    if (!wsPulseKey) return;
    const flashMap = {};
    stations.forEach((st) => {
      flashMap[st.station_id] = true;
    });
    setFlashingStations(flashMap);

    const timer = setTimeout(() => {
      setFlashingStations({});
    }, 700);

    return () => clearTimeout(timer);
  }, [wsPulseKey, stations]);

  const getStationStatus = (sid) => {
    const evalData = latestEvaluations[sid];
    if (!evalData) return { state: 'NOMINAL', label: 'ONLINE', color: 'border-slate-800 bg-[#0E1524]' };

    if (!evalData.is_anomaly) {
      return { state: 'NOMINAL', label: 'NOMINAL', color: 'border-slate-800 bg-[#0E1524]' };
    }

    const hardFaults = ['spike', 'dropout', 'inconsistency', 'stuck_sensor', 'frozen'];
    if (hardFaults.includes(evalData.anomaly_type?.toLowerCase())) {
      return { state: 'HARD_FAULT', label: evalData.anomaly_type.toUpperCase(), color: 'border-rose-600 bg-rose-950/20 hard-fault-pulse' };
    }

    if (evalData.confidence >= 0.75) {
      return { state: 'CORROBORATED_SOFT', label: evalData.anomaly_type.toUpperCase(), color: 'border-amber-500 bg-amber-950/20 soft-anomaly-pulse' };
    }

    return { state: 'ADVISORY', label: 'ADVISORY', color: 'border-yellow-600 bg-yellow-950/10' };
  };

  return (
    <div className="bg-[#0E1524] border border-slate-800 rounded-sm p-4 instrument-grid">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
        <h2 className="text-sm font-bold tracking-wider text-slate-100 uppercase font-mono flex items-center space-x-2">
          <span>DELHI-NCR AWS STATIONS (10 SENSORS)</span>
        </h2>
        <span className="text-xs font-mono text-slate-400">CLICK CARD TO INSPECT HISTORICAL TRENDS</span>
      </div>

      {/* 10-Station Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {stations.map((st) => {
          const sid = st.station_id;
          const status = getStationStatus(sid);
          const isSelected = selectedStationId === sid;
          const isFlashing = flashingStations[sid];
          const evalData = latestEvaluations[sid];

          return (
            <div
              key={sid}
              onClick={() => onSelectStation(sid)}
              className={`p-3 border rounded-sm transition-all duration-300 cursor-pointer select-none ${status.color} ${
                isSelected ? 'ring-2 ring-teal-500 border-teal-500' : 'hover:border-slate-600'
              } ${isFlashing ? 'ring-1 ring-teal-400/80 shadow-[0_0_12px_rgba(45,212,191,0.25)]' : ''}`}
            >
              {/* Station Header */}
              <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-slate-800/80">
                <span className="font-bold text-xs text-slate-100 font-mono tracking-tight truncate max-w-[110px]" title={st.name}>
                  {st.name}
                </span>

                <span
                  className={`text-[9px] font-mono px-1.5 py-0.5 rounded border uppercase font-semibold ${
                    status.state === 'HARD_FAULT'
                      ? 'bg-rose-900/80 text-rose-200 border-rose-600'
                      : status.state === 'CORROBORATED_SOFT'
                      ? 'bg-amber-900/80 text-amber-200 border-amber-500'
                      : status.state === 'ADVISORY'
                      ? 'bg-yellow-900/50 text-yellow-200 border-yellow-600'
                      : 'bg-teal-950/60 text-teal-300 border-teal-800'
                  }`}
                >
                  {status.label}
                </span>
              </div>

              {/* Live Telemetry Readings — Monospaced Numerals */}
              <div className="space-y-1.5 font-mono text-xs">
                {/* Temperature */}
                <div className="flex items-center justify-between text-slate-300">
                  <span className="flex items-center space-x-1 text-[11px] text-slate-400">
                    <Thermometer className="w-3 h-3 text-rose-400" />
                    <span>TEMP:</span>
                  </span>
                  <span className="font-bold text-slate-100">
                    {st.temperature !== null && st.temperature !== undefined
                      ? `${st.temperature.toFixed(1)}°C`
                      : 'NaN'}
                  </span>
                </div>

                {/* Pressure */}
                <div className="flex items-center justify-between text-slate-300">
                  <span className="flex items-center space-x-1 text-[11px] text-slate-400">
                    <Gauge className="w-3 h-3 text-teal-400" />
                    <span>PRES:</span>
                  </span>
                  <span className="font-semibold text-slate-200">
                    {st.pressure !== null && st.pressure !== undefined
                      ? `${st.pressure.toFixed(0)} hPa`
                      : 'NaN'}
                  </span>
                </div>

                {/* Humidity */}
                <div className="flex items-center justify-between text-slate-300">
                  <span className="flex items-center space-x-1 text-[11px] text-slate-400">
                    <Droplets className="w-3 h-3 text-cyan-400" />
                    <span>HUM:</span>
                  </span>
                  <span className="font-semibold text-slate-200">
                    {st.humidity !== null && st.humidity !== undefined
                      ? `${st.humidity.toFixed(0)}%`
                      : 'NaN'}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
