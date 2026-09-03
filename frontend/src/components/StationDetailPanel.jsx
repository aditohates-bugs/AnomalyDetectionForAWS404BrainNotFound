import React from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { Activity, MapPin, AlertTriangle, ShieldCheck, Clock } from 'lucide-react';

export default function StationDetailPanel({ station, history, stationAlerts, onClose }) {
  if (!station) return null;

  // Prepare chart data points
  const chartData = (history || []).map((r, i) => {
    let timeLabel = `#${i+1}`;
    if (r.timestamp) {
      const d = new Date(r.timestamp);
      timeLabel = !isNaN(d) ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : r.timestamp;
    }
    return {
      time: timeLabel,
      temp: r.temperature !== null && r.temperature !== undefined ? Number(r.temperature) : null,
      humidity: r.humidity !== null && r.humidity !== undefined ? Number(r.humidity) : null,
      pressure: r.pressure !== null && r.pressure !== undefined ? Number(r.pressure) : null,
    };
  });

  return (
    <div className="bg-[#0E1524] border border-slate-800 rounded-sm p-4 h-full flex flex-col instrument-grid select-none">
      {/* Station Inspector Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
        <div>
          <div className="flex items-center space-x-2">
            <MapPin className="w-4 h-4 text-teal-400" />
            <h3 className="text-sm font-bold text-slate-100 font-mono tracking-wide">
              {station.name.toUpperCase()} ({station.station_id})
            </h3>
          </div>
          <p className="text-[11px] font-mono text-slate-400 mt-0.5">
            LAT: {station.lat}°N | LON: {station.lon}°E | SENSOR STATUS: {station.status}
          </p>
        </div>

        {onClose && (
          <button
            onClick={onClose}
            className="text-xs font-mono px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700"
          >
            CLOSE
          </button>
        )}
      </div>

      {/* Recharts Historical Sparkline/Trend Chart */}
      <div className="mb-4 bg-black/40 border border-slate-800 p-3 rounded-sm">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-mono text-slate-400 font-bold uppercase flex items-center space-x-1.5">
            <Activity className="w-3.5 h-3.5 text-teal-400" />
            <span>TEMPERATURE TREND Sparkline (°C)</span>
          </span>
          <span className="text-[10px] font-mono text-slate-500">
            {chartData.length} TIMESTEPS PRE-SEEDED
          </span>
        </div>

        {chartData.length === 0 ? (
          <div className="h-28 flex items-center justify-center text-xs font-mono text-slate-500">
            Loading telemetry history...
          </div>
        ) : (
          <div className="h-28 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="2 2" stroke="#1E293B" />
                <XAxis dataKey="time" stroke="#64748B" fontSize={10} tickLine={false} />
                <YAxis stroke="#64748B" fontSize={10} domain={['auto', 'auto']} tickLine={false} width={30} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0F172A', borderColor: '#334155', fontSize: '11px', fontFamily: 'JetBrains Mono' }}
                  itemStyle={{ color: '#38BDF8' }}
                />
                <Line type="monotone" dataKey="temp" stroke="#0D9488" strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Station Event & Anomaly History Log */}
      <div className="flex-1 overflow-y-auto">
        <h4 className="text-xs font-mono font-bold text-slate-300 mb-2 uppercase flex items-center space-x-1.5">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
          <span>STATION MAINTENANCE & FLAG HISTORY ({stationAlerts.length})</span>
        </h4>

        {stationAlerts.length === 0 ? (
          <div className="p-3 border border-slate-800 bg-slate-900/30 text-xs font-mono text-slate-500 rounded">
            No historical anomalies recorded for this station during current session.
          </div>
        ) : (
          <div className="space-y-2">
            {stationAlerts.map((al, idx) => (
              <div key={idx} className="p-2.5 border border-slate-800 bg-slate-900/50 rounded text-xs font-mono space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-amber-400">{al.anomaly_type?.toUpperCase()}</span>
                  <span className="text-[10px] text-slate-500">{al.timestamp}</span>
                </div>
                <p className="text-[11px] font-sans text-slate-300">{al.reason}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
