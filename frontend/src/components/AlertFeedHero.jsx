import React from 'react';
import { AlertOctagon, AlertTriangle, Info, CheckCircle2, ShieldAlert, Cpu } from 'lucide-react';

export default function AlertFeedHero({ alerts, onSelectStation }) {
  // Helper to determine 3-tier visual severity class
  const getSeverityTier = (alert) => {
    if (!alert.is_anomaly) return 'NOMINAL';
    
    const hardFaults = ['spike', 'dropout', 'inconsistency', 'stuck_sensor', 'frozen'];
    if (hardFaults.includes(alert.anomaly_type?.toLowerCase())) {
      return 'HARD_FAULT'; // Tier 1: Emergency Hard Physical Fault (Red)
    }
    
    // Check if reason or confidence indicates multi-layer corroboration vs single-layer
    if (alert.confidence >= 0.75 || (alert.reason && alert.reason.includes('corroborated'))) {
      return 'CORROBORATED_SOFT'; // Tier 2: Corroborated Soft Statistical Anomaly (Amber)
    }
    
    return 'SINGLE_LAYER_ADVISORY'; // Tier 3: Single-layer statistical flag for review (Yellow)
  };

  return (
    <div className="bg-[#0E1524] border border-slate-800 rounded-sm p-4 flex flex-col h-full instrument-grid">
      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
        <div className="flex items-center space-x-2">
          <ShieldAlert className="w-5 h-5 text-rose-500" />
          <h2 className="text-sm font-bold tracking-wider text-slate-100 uppercase">
            LIVE ANOMALY REASONING & EVALUATION STREAM
          </h2>
        </div>
        <div className="flex items-center space-x-3 text-[11px] font-mono">
          <span className="flex items-center space-x-1 text-rose-400">
            <span className="w-2 h-2 rounded-full bg-rose-500" />
            <span>HARD FAULT</span>
          </span>
          <span className="flex items-center space-x-1 text-amber-400">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            <span>CORROBORATED SOFT</span>
          </span>
          <span className="flex items-center space-x-1 text-yellow-400">
            <span className="w-2 h-2 rounded-full bg-yellow-500" />
            <span>ADVISORY (REVIEW)</span>
          </span>
        </div>
      </div>

      {/* Alert Feed Stream Box */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {alerts.length === 0 ? (
          <div className="h-full min-h-[160px] flex flex-col items-center justify-center text-slate-500 text-xs font-mono space-y-2 border border-dashed border-slate-800 rounded p-6">
            <CheckCircle2 className="w-8 h-8 text-teal-600/60" />
            <p className="text-slate-400 font-medium">ALL 10 DELHI AWS STATIONS NOMINAL — 0 ACTIVE FAULTS</p>
            <p className="text-slate-600 text-[11px]">Streaming live Open-Meteo evaluations over WebSockets...</p>
          </div>
        ) : (
          alerts.map((alert, idx) => {
            const tier = getSeverityTier(alert);
            
            let cardBg = 'bg-slate-900/60 border-slate-800';
            let icon = <Info className="w-4 h-4 text-slate-400" />;
            let badgeBg = 'bg-slate-800 text-slate-300 border-slate-700';
            let pulseClass = '';

            if (tier === 'HARD_FAULT') {
              cardBg = 'bg-rose-950/30 border-rose-600/80 text-rose-100';
              badgeBg = 'bg-rose-900/80 text-rose-200 border-rose-600 font-bold';
              icon = <AlertOctagon className="w-5 h-5 text-rose-500 flex-shrink-0" />;
              pulseClass = 'hard-fault-pulse';
            } else if (tier === 'CORROBORATED_SOFT') {
              cardBg = 'bg-amber-950/30 border-amber-500/70 text-amber-100';
              badgeBg = 'bg-amber-900/80 text-amber-200 border-amber-500 font-bold';
              icon = <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0" />;
              pulseClass = 'soft-anomaly-pulse';
            } else if (tier === 'SINGLE_LAYER_ADVISORY') {
              cardBg = 'bg-yellow-950/20 border-yellow-600/50 text-yellow-100';
              badgeBg = 'bg-yellow-900/50 text-yellow-200 border-yellow-600 font-medium';
              icon = <Info className="w-5 h-5 text-yellow-500 flex-shrink-0" />;
            }

            return (
              <div
                key={idx}
                onClick={() => onSelectStation(alert.station_id)}
                className={`p-3.5 border rounded-sm transition-all duration-200 cursor-pointer hover:brightness-110 ${cardBg} ${pulseClass}`}
              >
                {/* Station & Anomaly Header Row */}
                <div className="flex items-center justify-between gap-2 mb-2 font-mono">
                  <div className="flex items-center space-x-2.5">
                    {icon}
                    <span className="font-bold text-sm tracking-wide text-slate-100">
                      {alert.station_id.toUpperCase().replace('_', ' ')}
                    </span>
                    <span className={`text-[10px] px-2 py-0.5 border rounded uppercase ${badgeBg}`}>
                      {alert.anomaly_type || 'FLAGGED'}
                    </span>
                  </div>

                  <div className="flex items-center space-x-3 text-xs">
                    {/* Confidence Meter */}
                    <div className="flex items-center space-x-1.5" title="Detector Evaluation Confidence">
                      <span className="text-slate-400 text-[10px]">CONF:</span>
                      <span className="font-bold text-slate-200">
                        {Math.round((alert.confidence || 0) * 100)}%
                      </span>
                    </div>
                    <span className="text-slate-500 text-[10px]">{alert.timestamp}</span>
                  </div>
                </div>

                {/* FULL DIAGNOSTIC REASONING SENTENCE — CORE REQUIREMENT */}
                <div className="text-xs leading-relaxed font-sans text-slate-200 bg-black/40 p-2.5 border border-slate-800/80 rounded-sm">
                  <span className="font-mono text-[10px] text-teal-400 font-semibold uppercase block mb-1">
                    ROOT CAUSE DIAGNOSIS:
                  </span>
                  <p>{alert.reason || 'Sensor deviation evaluated by detector.'}</p>
                </div>

                {/* Feature Contribution Attribution readout if available */}
                {alert.feature_contribution && (
                  <div className="mt-1 text-[10px] font-mono text-slate-400 flex items-center space-x-2 bg-slate-900/60 px-2.5 py-1 border border-slate-800/60 rounded-sm">
                    <span className="text-teal-400/90 font-semibold uppercase">ATTRIBUTION:</span>
                    <span>
                      {Object.entries(alert.feature_contribution).map(([k, v]) => `${k}: ${Math.round(v * 100)}%`).join(' | ')}
                    </span>
                  </div>
                )}

                {/* Corrected Value Readout if available */}
                {alert.corrected_value && (
                  <div className="mt-1 text-[11px] font-mono text-teal-400/90 flex items-center space-x-2 bg-teal-950/30 px-2.5 py-1 border border-teal-800/50 rounded-sm">
                    <Cpu className="w-3.5 h-3.5 text-teal-400" />
                    <span>ESTIMATED CORRECTED VALUE:</span>
                    <span className="font-bold text-slate-100">
                      {Object.entries(alert.corrected_value).map(([k, v]) => `${k}=${v.toFixed(1)}`).join(' | ')}
                    </span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
