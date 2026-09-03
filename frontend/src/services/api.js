/**
 * Backend API Client & WebSocket Alert Manager
 * Connects to REST endpoints (/stations, /health, /inject-fault)
 * and streams real-time WebSocket alert evaluation payloads (/ws/alerts).
 */

const API_BASE = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws/alerts';

export async function fetchStations() {
  const resp = await fetch(`${API_BASE}/stations`);
  if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
  return await resp.json();
}

export async function fetchHealth() {
  const resp = await fetch(`${API_BASE}/health`);
  if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
  return await resp.json();
}

export async function fetchAllStationsHistory(hours = 48) {
  const resp = await fetch(`${API_BASE}/stations/history?hours=${hours}`);
  if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
  return await resp.json();
}

export async function fetchStationHistory(stationId, hours = 48) {
  const resp = await fetch(`${API_BASE}/stations/${stationId}/history?hours=${hours}`);
  if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
  return await resp.json();
}

export async function injectFault(stationId, faultType) {
  const resp = await fetch(`${API_BASE}/inject-fault`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      station_id: stationId,
      fault_type: faultType
    })
  });
  if (!resp.ok) {
    const err = await resp.json();
    throw new Error(err.detail || 'Failed to inject fault');
  }
  return await resp.json();
}

export function connectAlertWebSocket(onMessage, onError, onClose) {
  let ws = null;
  let retryTimer = null;
  let isIntentionallyClosed = false;

  function connect() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log('[WS] Connected to Delhi AWS Alert Stream');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (err) {
        console.error('[WS] Parse error:', err);
      }
    };

    ws.onerror = (err) => {
      console.error('[WS] Error:', err);
      if (onError) onError(err);
    };

    ws.onclose = () => {
      console.log('[WS] Connection closed');
      if (onClose) onClose();
      if (!isIntentionallyClosed) {
        retryTimer = setTimeout(() => {
          console.log('[WS] Attempting reconnect...');
          connect();
        }, 3000);
      }
    };
  }

  connect();

  return () => {
    isIntentionallyClosed = true;
    if (retryTimer) clearTimeout(retryTimer);
    if (ws) ws.close();
  };
}
