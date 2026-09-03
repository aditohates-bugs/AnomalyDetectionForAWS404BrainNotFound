import React, { useState } from 'react';
import { Zap, AlertTriangle, ShieldCheck, Flame, Radio } from 'lucide-react';
import { injectFault } from '../services/api';

export default function FaultInjectorPanel({ stations, onFaultQueued }) {
  const [selectedStation, setSelectedStation] = useState(stations[0]?.station_id || 'igi_airport');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState(null);

  const handleTrigger = async (faultType, label) => {
    setIsSubmitting(true);
    setStatusMsg(null);
    try {
      const res = await injectFault(selectedStation, faultType);
      setStatusMsg({ type: 'SUCCESS', text: `[QUEUED] ${label} fault injected into ${selectedStation.toUpperCase()}. Applying on next tick!` });
      if (onFaultQueued) onFaultQueued(selectedStation, faultType);
    } catch (err) {
      setStatusMsg({ type: 'ERROR', text: `[FAILED] ${err.message}` });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-[#0E1524] border border-slate-800 rounded-sm p-4 instrument-grid select-none">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
        <div className="flex items-center space-x-2">
          <Zap className="w-4 h-4 text-amber-400" />
          <h2 className="text-sm font-bold tracking-wider text-slate-100 uppercase font-mono">
            SYNTHETIC FAULT INJECTOR CONSOLE (LIVE DEMO TRIGGER)
          </h2>
        </div>

        {/* Target Station Selector */}
        <div className="flex items-center space-x-2">
          <label className="text-xs font-mono text-slate-400">TARGET STATION:</label>
          <select
            value={selectedStation}
            onChange={(e) => setSelectedStation(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-slate-100 text-xs font-mono rounded px-2.5 py-1 focus:outline-none focus:border-teal-500"
          >
            {stations.map((s) => (
              <option key={s.station_id} value={s.station_id}>
                {s.name} ({s.station_id})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Action Buttons Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* PRIMARY CONFIRMED LINEUP (95-100% RELIABILITY) */}
        <div className="space-y-2">
          <div className="flex items-center space-x-1.5 text-[11px] font-mono text-teal-400 font-bold uppercase">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>PRIMARY DEMO LINEUP (100% CATCH RATE)</span>
          </div>

          <div className="grid grid-cols-2 gap-2 font-mono text-xs">
            <button
              disabled={isSubmitting}
              onClick={() => handleTrigger('spike', 'Unphysical Spike')}
              className="p-2 bg-rose-950/60 hover:bg-rose-900 border border-rose-600/80 text-rose-200 font-bold rounded flex items-center justify-center space-x-1.5 transition-all disabled:opacity-50"
            >
              <Flame className="w-3.5 h-3.5 text-rose-400" />
              <span>INJECT SPIKE</span>
            </button>

            <button
              disabled={isSubmitting}
              onClick={() => handleTrigger('dropout', 'Telemetry Dropout')}
              className="p-2 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-200 font-bold rounded flex items-center justify-center space-x-1.5 transition-all disabled:opacity-50"
            >
              <Radio className="w-3.5 h-3.5 text-slate-400" />
              <span>INJECT DROPOUT</span>
            </button>

            <button
              disabled={isSubmitting}
              onClick={() => handleTrigger('inconsistency', 'Dew Point Breach')}
              className="p-2 bg-amber-950/60 hover:bg-amber-900 border border-amber-500/80 text-amber-200 font-bold rounded flex items-center justify-center space-x-1.5 transition-all disabled:opacity-50"
            >
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span>DEW-POINT FAULT</span>
            </button>

            <button
              disabled={isSubmitting}
              onClick={() => handleTrigger('frozen', 'Stuck Sensor Flatline')}
              className="p-2 bg-cyan-950/60 hover:bg-cyan-900 border border-cyan-700 text-cyan-200 font-bold rounded flex items-center justify-center space-x-1.5 transition-all disabled:opacity-50"
            >
              <Zap className="w-3.5 h-3.5 text-cyan-400" />
              <span>STUCK SENSOR</span>
            </button>
          </div>
        </div>

        {/* SECONDARY ADVANCED SIGNALS (70-80% RELIABILITY) */}
        <div className="space-y-2">
          <div className="flex items-center space-x-1.5 text-[11px] font-mono text-slate-400 font-bold uppercase">
            <AlertTriangle className="w-3.5 h-3.5 text-yellow-500" />
            <span>ADVANCED STATISTICAL SIGNALS (70-80% CATCH)</span>
          </div>

          <div className="grid grid-cols-2 gap-2 font-mono text-xs">
            <button
              disabled={isSubmitting}
              onClick={() => handleTrigger('spatial_outlier', 'Spatial Divergence')}
              className="p-2 bg-slate-900 hover:bg-slate-800 border border-yellow-700/60 text-yellow-200 font-medium rounded flex items-center justify-center space-x-1.5 transition-all disabled:opacity-50"
            >
              <span>SPATIAL OUTLIER</span>
            </button>

            <button
              disabled={isSubmitting}
              onClick={() => handleTrigger('drift', 'Calibration Stray')}
              className="p-2 bg-slate-900 hover:bg-slate-800 border border-yellow-700/60 text-yellow-200 font-medium rounded flex items-center justify-center space-x-1.5 transition-all disabled:opacity-50"
            >
              <span>DRIFT FAULT</span>
            </button>
          </div>
        </div>
      </div>

      {/* Queue Status Notification */}
      {statusMsg && (
        <div
          className={`mt-3 p-2 text-xs font-mono rounded border ${
            statusMsg.type === 'SUCCESS'
              ? 'bg-teal-950/80 text-teal-200 border-teal-600'
              : 'bg-rose-950/80 text-rose-200 border-rose-600'
          }`}
        >
          {statusMsg.text}
        </div>
      )}
    </div>
  );
}
