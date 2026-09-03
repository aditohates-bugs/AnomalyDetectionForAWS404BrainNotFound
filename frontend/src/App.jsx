import React, { useState, useEffect } from 'react';
import HeaderHealthStrip from './components/HeaderHealthStrip';
import AlertFeedHero from './components/AlertFeedHero';
import StationDetailPanel from './components/StationDetailPanel';
import MultiStationTelemetryStrip from './components/MultiStationTelemetryStrip';
import StationGrid from './components/StationGrid';
import FaultInjectorPanel from './components/FaultInjectorPanel';
import { fetchStations, fetchHealth, fetchAllStationsHistory, connectAlertWebSocket } from './services/api';

export default function App() {
  const [stations, setStations] = useState([]);
  const [health, setHealth] = useState(null);
  const [isWsConnected, setIsWsConnected] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const [latestEvaluations, setLatestEvaluations] = useState({});
  const [stationHistories, setStationHistories] = useState({});
  const [selectedStationId, setSelectedStationId] = useState('igi_airport');
  const [wsPulseKey, setWsPulseKey] = useState(0);

  // Initial REST fetch & pre-seed historical dataset
  useEffect(() => {
    async function loadInitial() {
      try {
        const stData = await fetchStations();
        setStations(stData.stations || []);
        
        const hData = await fetchHealth();
        setHealth(hData);

        // Pre-seed 48-hour historical telemetry for all stations
        const histData = await fetchAllStationsHistory(48);
        if (histData && histData.history) {
          setStationHistories(histData.history);
        }
      } catch (err) {
        console.error('Failed initial REST fetch:', err);
      }
    }
    loadInitial();

    const healthInterval = setInterval(async () => {
      try {
        const hData = await fetchHealth();
        setHealth(hData);
      } catch (e) {}
    }, 5000);

    return () => clearInterval(healthInterval);
  }, []);

  // WebSocket Live Alert Stream listener
  useEffect(() => {
    const disconnect = connectAlertWebSocket(
      (msg) => {
        if (msg.event === 'CONNECTED') {
          setIsWsConnected(true);
        } else if (msg.event === 'POLL_UPDATE') {
          setIsWsConnected(true);
          setWsPulseKey(Date.now());
          
          // Update live station readings
          if (msg.readings) {
            setStations((prevStations) =>
              prevStations.map((st) => {
                const liveR = msg.readings[st.station_id];
                if (liveR) {
                  return {
                    ...st,
                    temperature: liveR.temperature,
                    pressure: liveR.pressure,
                    humidity: liveR.humidity,
                    last_updated: liveR.timestamp
                  };
                }
                return st;
              })
            );

            // Buffer historical trend points per station (appending live WS ticks)
            setStationHistories((prev) => {
              const updated = { ...prev };
              Object.entries(msg.readings).forEach(([sid, r]) => {
                const buf = updated[sid] ? [...updated[sid]] : [];
                buf.push(r);
                if (buf.length > 96) buf.shift(); // Keep up to 96 points (~48h)
                updated[sid] = buf;
              });
              return updated;
            });
          }

          // Process evaluations & prepend anomalies to alert stream
          if (msg.evaluations) {
            setLatestEvaluations(msg.evaluations);

            const newAnomalies = [];
            Object.values(msg.evaluations).forEach((ev) => {
              if (ev.is_anomaly) {
                newAnomalies.push(ev);
              }
            });

            if (newAnomalies.length > 0) {
              setAlerts((prevAlerts) => [...newAnomalies, ...prevAlerts].slice(0, 50));
            }
          }
        }
      },
      (err) => setIsWsConnected(false),
      () => setIsWsConnected(false)
    );

    return () => disconnect();
  }, []);

  const selectedStationObj = stations.find((s) => s.station_id === selectedStationId);
  const selectedHistory = stationHistories[selectedStationId] || [];
  const selectedStationAlerts = alerts.filter((a) => a.station_id === selectedStationId);

  return (
    <div className="min-h-screen bg-[#080C14] text-slate-100 flex flex-col font-sans">
      {/* 1. Header Health Strip */}
      <HeaderHealthStrip
        health={health}
        isWsConnected={isWsConnected}
        wsPulseKey={wsPulseKey}
      />

      {/* Main Mission-Control Dashboard Layout */}
      <main className="flex-1 p-4 grid grid-cols-1 lg:grid-cols-12 gap-4 max-w-[1800px] w-full mx-auto">
        {/* HERO SECTION (Left / Top 7 cols): Live Anomaly Reasoning Stream */}
        <div className="lg:col-span-7 h-[420px]">
          <AlertFeedHero
            alerts={alerts}
            onSelectStation={(sid) => setSelectedStationId(sid)}
          />
        </div>

        {/* AUXILIARY SECTION (Right 5 cols): Station Detail Inspector */}
        <div className="lg:col-span-5 h-[420px]">
          <StationDetailPanel
            station={selectedStationObj}
            history={selectedHistory}
            stationAlerts={selectedStationAlerts}
          />
        </div>

        {/* ALWAYS-MOVING TELEMETRY HERO PANEL (12 cols): Multi-Station Temperature Strip */}
        <div className="lg:col-span-12 h-[260px]">
          <MultiStationTelemetryStrip
            stationHistories={stationHistories}
            isWsConnected={isWsConnected}
          />
        </div>

        {/* MAIN SECTION (12 cols): 10-Station Telemetry Grid */}
        <div className="lg:col-span-12">
          <StationGrid
            stations={stations}
            latestEvaluations={latestEvaluations}
            selectedStationId={selectedStationId}
            onSelectStation={(sid) => setSelectedStationId(sid)}
            wsPulseKey={wsPulseKey}
          />
        </div>

        {/* CONTROL SECTION (12 cols): Fault Injector Panel */}
        <div className="lg:col-span-12">
          <FaultInjectorPanel
            stations={stations}
            onFaultQueued={(sid, ftype) => {
              console.log(`Fault ${ftype} queued for station ${sid}`);
            }}
          />
        </div>
      </main>
    </div>
  );
}
