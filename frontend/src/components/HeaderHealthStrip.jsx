import React, { useState, useEffect } from 'react';
import { Activity, ShieldCheck, Database, RefreshCw, AlertTriangle, Clock, Server } from 'lucide-react';

export default function HeaderHealthStrip({ health, isWsConnected, wsPulseKey }) {
  const modelLoaded = health?.model_loaded ?? false;
  const fallbackCount = health?.fallback_count ?? 0;
  const uptime = health?.uptime_seconds ? Math.floor(health.uptime_seconds) : 0;
  const totalPolls = health?.total_polls ?? 0;
  const totalAlerts = health?.total_alerts ?? 0;

  // Discrete flash trigger when a real WS message is received
  const [isFlashing, setIsFlashing] = useState(false);

  useEffect(() => {
    if (!wsPulseKey) return;
    setIsFlashing(true);
    const timer = setTimeout(() => setIsFlashing(false), 500);
    return () => clearTimeout(timer);
  }, [wsPulseKey]);

  return (
    <header className="bg-[#0E1524] border-b border-slate-800 text-xs px-4 py-2 flex flex-wrap items-center justify-between gap-4 font-mono select-none">
      {/* Brand & System Mode */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center space-x-2">
          {/* Connection Dot: flashes brightly ONLY on real WebSocket event */}
          <div
            className={`w-2.5 h-2.5 rounded-full transition-all duration-300 ${
              isWsConnected
                ? isFlashing
                  ? 'bg-teal-300 scale-150 shadow-[0_0_8px_#2dd4bf]'
                  : 'bg-teal-500'
                : 'bg-rose-500'
            }`}
          />
          <span className="font-bold text-slate-100 tracking-wider text-sm">DELHI-NCR AWS MISSION CONTROL</span>
        </div>
        <span className="text-slate-600">|</span>
        <span className="text-slate-400 font-semibold">SIH26073 ANOMALY CORE v2.0</span>
      </div>

      {/* Understated Diagnostic Metrics */}
      <div className="flex flex-wrap items-center space-x-6 text-slate-300">
        {/* WebSocket Stream Status */}
        <div className="flex items-center space-x-1.5" title="WebSocket Live Stream Status">
          <Activity className={`w-3.5 h-3.5 ${isWsConnected ? (isFlashing ? 'text-teal-200 scale-110 transition-transform' : 'text-teal-400') : 'text-amber-500 animate-spin'}`} />
          <span className="text-slate-400">STREAM:</span>
          <span className={isWsConnected ? 'text-teal-400 font-bold' : 'text-amber-500 font-bold'}>
            {isWsConnected ? 'CONNECTED (LIVE)' : 'RECONNECTING'}
          </span>
        </div>

        {/* PyTorch Model State */}
        <div className="flex items-center space-x-1.5" title="PyTorch LSTM-Autoencoder Learned Model Status">
          <ShieldCheck className={`w-3.5 h-3.5 ${modelLoaded ? 'text-teal-400' : 'text-amber-500'}`} />
          <span className="text-slate-400">MODEL:</span>
          <span className={modelLoaded ? 'text-teal-400 font-semibold' : 'text-amber-500 font-semibold'}>
            {modelLoaded ? 'LSTM-AE (ENABLED)' : 'RULE-ONLY'}
          </span>
        </div>

        {/* Live Open-Meteo Poll Status */}
        <div className="flex items-center space-x-1.5" title="Total Live Poll Rounds Executed">
          <RefreshCw className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-slate-400">POLLS:</span>
          <span className="text-slate-200 font-mono font-bold">{totalPolls}</span>
        </div>

        {/* Fallback Count */}
        <div className="flex items-center space-x-1.5" title="Open-Meteo Network Fallback Events">
          <Database className={`w-3.5 h-3.5 ${fallbackCount > 0 ? 'text-amber-400' : 'text-slate-500'}`} />
          <span className="text-slate-400">FALLBACKS:</span>
          <span className={`font-mono font-bold ${fallbackCount > 0 ? 'text-amber-400' : 'text-slate-300'}`}>
            {fallbackCount}
          </span>
        </div>

        {/* Total Evaluated Anomaly Alerts */}
        <div className="flex items-center space-x-1.5" title="Total Anomaly Flags Evaluated">
          <AlertTriangle className={`w-3.5 h-3.5 ${totalAlerts > 0 ? 'text-crimson-400' : 'text-slate-500'}`} />
          <span className="text-slate-400">ALERTS:</span>
          <span className={`font-mono font-bold ${totalAlerts > 0 ? 'text-rose-400' : 'text-slate-300'}`}>
            {totalAlerts}
          </span>
        </div>

        {/* Uptime */}
        <div className="flex items-center space-x-1.5" title="Backend Server Uptime">
          <Clock className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-slate-400">UPTIME:</span>
          <span className="text-slate-300 font-mono">{uptime}s</span>
        </div>
      </div>
    </header>
  );
}
