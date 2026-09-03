import React, { useState, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { Activity, Layers, Radio, Check } from 'lucide-react';

const STATION_COLORS = {
  igi_airport: '#10B981',      // Emerald
  lodhi_road: '#3B82F6',       // Blue
  red_fort: '#F59E0B',         // Amber
  qutab_minar: '#EC4899',      // Pink
  chandni_chowk: '#8B5CF6',    // Purple
  akshardham: '#06B6D4',       // Cyan
  lotus_temple: '#F97316',     // Orange
  delhi_university: '#84CC16', // Lime
  ndls: '#E11D48',             // Rose
  pragati_maidan: '#14B8A6'    // Teal
};

const STATION_NAMES = {
  igi_airport: 'IGI Airport',
  lodhi_road: 'Lodhi Road',
  red_fort: 'Red Fort',
  qutab_minar: 'Qutab Minar',
  chandni_chowk: 'Chandni Chowk',
  akshardham: 'Akshardham',
  lotus_temple: 'Lotus Temple',
  delhi_university: 'Delhi Univ.',
  ndls: 'NDLS',
  pragati_maidan: 'Pragati Maidan'
};

export default function MultiStationTelemetryStrip({ stationHistories, isWsConnected }) {
  const stationIds = Object.keys(STATION_COLORS);

  // Active visible station line toggles
  const [visibleStations, setVisibleStations] = useState(
    stationIds.reduce((acc, sid) => ({ ...acc, [sid]: true }), {})
  );

  const toggleStation = (sid) => {
    setVisibleStations((prev) => ({ ...prev, [sid]: !prev[sid] }));
  };

  // Transform station histories into unified multi-line time series chart dataset
  const combinedChartData = useMemo(() => {
    if (!stationHistories || Object.keys(stationHistories).length === 0) return [];

    // Collect all unique timestamps from all histories
    const timeMap = {}; // { timestampKey: { timeLabel, timestamp, [sid]: temp } }

    Object.entries(stationHistories).forEach(([sid, records]) => {
      (records || []).forEach((r) => {
        if (!r.timestamp || r.temperature === null || r.temperature === undefined) return;
        const tsKey = r.timestamp;
        if (!timeMap[tsKey]) {
          const dateObj = new Date(r.timestamp);
          const timeLabel = !isNaN(dateObj)
            ? dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            : r.timestamp;
          timeMap[tsKey] = { tsKey, time: timeLabel };
        }
        timeMap[tsKey][sid] = Number(r.temperature);
      });
    });

    // Sort chronologically and take up to last 48 points for fluid telemetry motion
    const sorted = Object.values(timeMap).sort((a, b) => (a.tsKey > b.tsKey ? 1 : -1));
    return sorted.slice(-48);
  }, [stationHistories]);

  return (
    <div className="bg-[#0E1524] border border-slate-800 rounded-sm p-4 instrument-grid select-none flex flex-col h-full">
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between border-b border-slate-800 pb-3 mb-3 gap-2">
        <div className="flex items-center space-x-2">
          <Layers className="w-4 h-4 text-teal-400" />
          <h2 className="text-sm font-bold tracking-wider text-slate-100 uppercase font-mono">
            MULTI-STATION REAL-TIME TELEMETRY STRIP (ALL 10 SENSORS)
          </h2>
        </div>

        <div className="flex items-center space-x-3 text-xs font-mono">
          <span className="flex items-center space-x-1.5 text-slate-400">
            <Radio className={`w-3.5 h-3.5 ${isWsConnected ? 'text-teal-400' : 'text-amber-500'}`} />
            <span>STREAM CADENCE: <strong className="text-slate-200">LIVE TICK</strong></span>
          </span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-400">BUFFERED: <strong className="text-teal-400">{combinedChartData.length} TIMESTEPS</strong></span>
        </div>
      </div>

      {/* Station Visibility Legend Pill Toggles */}
      <div className="flex flex-wrap gap-1.5 mb-3 text-[11px] font-mono">
        {stationIds.map((sid) => {
          const isVisible = visibleStations[sid];
          const color = STATION_COLORS[sid];
          return (
            <button
              key={sid}
              onClick={() => toggleStation(sid)}
              className={`px-2 py-0.5 rounded border transition-all flex items-center space-x-1.5 ${
                isVisible
                  ? 'bg-slate-900 text-slate-200 border-slate-700 font-semibold'
                  : 'bg-slate-950/40 text-slate-600 border-slate-900 opacity-60'
              }`}
            >
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ backgroundColor: isVisible ? color : '#475569' }}
              />
              <span>{STATION_NAMES[sid]}</span>
            </button>
          );
        })}
      </div>

      {/* Main Multi-Line Telemetry Recharts Box */}
      <div className="flex-1 w-full min-h-[160px] bg-black/40 border border-slate-800/90 p-2 rounded-sm relative">
        {combinedChartData.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs font-mono text-slate-500">
            Initializing continuous multi-station telemetry waveform...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={combinedChartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 2" stroke="#1E293B" />
              <XAxis
                dataKey="time"
                stroke="#64748B"
                fontSize={10}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                stroke="#64748B"
                fontSize={10}
                domain={['auto', 'auto']}
                tickLine={false}
                width={35}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0F172A',
                  borderColor: '#334155',
                  fontSize: '11px',
                  fontFamily: 'JetBrains Mono'
                }}
                itemStyle={{ fontSize: '10px' }}
              />
              {stationIds.map((sid) => (
                visibleStations[sid] && (
                  <Line
                    key={sid}
                    type="monotone"
                    dataKey={sid}
                    name={STATION_NAMES[sid]}
                    stroke={STATION_COLORS[sid]}
                    strokeWidth={1.8}
                    dot={false}
                    activeDot={{ r: 3.5 }}
                    isAnimationActive={false}
                  />
                )
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
