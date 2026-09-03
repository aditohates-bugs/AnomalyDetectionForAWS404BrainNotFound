"""
PyTorch LSTM-Autoencoder Anomaly Detection Engine
=================================================
Learns station-specific normal meteorological dynamics across 10 Delhi-NCR AWS stations.
Includes:
  - Sliding window dataset generation (24-hour windows)
  - Station identity one-hot encoding & per-station feature scaling
  - Disaster-window oversampling/upweighting during training
  - Per-station K-sigma threshold setting on validation split
  - Per-variable reconstruction error decomposition for explainability
"""

import os
import pickle
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from typing import Dict, Tuple, List, Optional

STATION_IDS = [
    "igi_airport", "lodhi_road", "red_fort", "qutab_minar", "chandni_chowk",
    "akshardham", "lotus_temple", "delhi_university", "ndls", "pragati_maidan"
]
STATION_INDEX = {sid: i for i, sid in enumerate(STATION_IDS)}

FEATURE_COLS = ["temperature", "pressure", "humidity"]
WINDOW_SIZE = 24  # 24 hours rolling window
NUM_STATIONS = len(STATION_IDS)
NUM_FEATURES = len(FEATURE_COLS)
INPUT_DIM = NUM_FEATURES + NUM_STATIONS  # 3 features + 10-dim station one-hot


class LSTMAutoencoder(nn.Module):
    def __init__(self, input_dim: int = INPUT_DIM, hidden_dim: int = 32, num_layers: int = 1):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers

        # Encoder
        self.encoder = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True
        )

        # Decoder
        self.decoder = nn.LSTM(
            input_size=hidden_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True
        )

        # Reconstruction Output Head (predicts 3 sensor values: temp, pres, hum)
        self.output_layer = nn.Linear(hidden_dim, NUM_FEATURES)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x shape: (batch, window_size, input_dim)
        _, (h_n, _) = self.encoder(x)
        # h_n shape: (num_layers, batch, hidden_dim)
        # Repeat bottleneck vector across sequence length
        bottleneck = h_n[-1].unsqueeze(1).repeat(1, x.size(1), 1)
        dec_out, _ = self.decoder(bottleneck)
        rec_features = self.output_layer(dec_out)  # (batch, window_size, 3)
        return rec_features


class PerStationScaler:
    def __init__(self):
        self.params: Dict[str, Dict[str, Tuple[float, float]]] = {}

    def fit(self, station_history: Dict[str, pd.DataFrame]):
        for sid, df in station_history.items():
            self.params[sid] = {}
            for col in FEATURE_COLS:
                min_v = float(df[col].min())
                max_v = float(df[col].max())
                if max_v - min_v < 1e-5:
                    max_v = min_v + 1.0
                self.params[sid][col] = (min_v, max_v)

    def transform_row(self, sid: str, temp: float, pres: float, hum: float) -> np.ndarray:
        if sid not in self.params:
            p_t, p_p, p_h = (0.0, 50.0), (950.0, 1030.0), (0.0, 100.0)
        else:
            p_t = self.params[sid]["temperature"]
            p_p = self.params[sid]["pressure"]
            p_h = self.params[sid]["humidity"]

        t_norm = (temp - p_t[0]) / (p_t[1] - p_t[0])
        p_norm = (pres - p_p[0]) / (p_p[1] - p_p[0])
        h_norm = (hum - p_h[0]) / (p_h[1] - p_h[0])

        return np.clip(np.array([t_norm, p_norm, h_norm], dtype=np.float32), 0.0, 1.0)

    def inverse_transform_row(self, sid: str, norm_vec: np.ndarray) -> np.ndarray:
        if sid not in self.params:
            p_t, p_p, p_h = (0.0, 50.0), (950.0, 1030.0), (0.0, 100.0)
        else:
            p_t = self.params[sid]["temperature"]
            p_p = self.params[sid]["pressure"]
            p_h = self.params[sid]["humidity"]

        temp = norm_vec[0] * (p_t[1] - p_t[0]) + p_t[0]
        pres = norm_vec[1] * (p_p[1] - p_p[0]) + p_p[0]
        hum = norm_vec[2] * (p_h[1] - p_h[0]) + p_h[0]
        return np.array([temp, pres, hum], dtype=np.float32)


def build_sliding_windows(
    station_history: Dict[str, pd.DataFrame],
    scaler: PerStationScaler,
    window_size: int = WINDOW_SIZE,
    oversample_extreme: bool = True,
    step: int = 1
) -> Tuple[np.ndarray, List[str]]:
    """Generates (N, window_size, 13) input arrays and station IDs."""
    window_list = []
    station_list = []

    for sid, df in station_history.items():
        if len(df) < window_size:
            continue
        st_idx = STATION_INDEX.get(sid, 0)
        one_hot = np.zeros(NUM_STATIONS, dtype=np.float32)
        one_hot[st_idx] = 1.0

        # Transform all rows for this station
        feats = []
        for _, row in df.iterrows():
            f_norm = scaler.transform_row(sid, row["temperature"], row["pressure"], row["humidity"])
            vec = np.concatenate([f_norm, one_hot])
            feats.append(vec)
        feats_arr = np.array(feats, dtype=np.float32)

        # Sliding windows
        n_windows = len(feats_arr) - window_size + 1
        for i in range(0, n_windows, step):
            w = feats_arr[i : i + window_size]
            window_list.append(w)
            station_list.append(sid)

            # Disaster Window Oversampling during training
            if oversample_extreme:
                window_raw_t = df.iloc[i : i + window_size]["temperature"].values
                if np.any(window_raw_t >= 40.0) or np.any(window_raw_t <= 7.0):
                    for _ in range(2):  # Oversample 2 extra times
                        window_list.append(w)
                        station_list.append(sid)

    return np.array(window_list, dtype=np.float32), station_list


class WindowDataset(Dataset):
    def __init__(self, windows: np.ndarray):
        self.windows = torch.from_numpy(windows)

    def __len__(self):
        return len(self.windows)

    def __getitem__(self, idx):
        x = self.windows[idx]
        y = x[:, :NUM_FEATURES]
        return x, y


def train_lstm_autoencoder(
    train_history: Dict[str, pd.DataFrame],
    val_history: Dict[str, pd.DataFrame],
    epochs: int = 10,
    batch_size: int = 512,
    lr: float = 0.003,
    model_save_path: str = "detector/lstm_ae_model.pth",
    config_save_path: str = "detector/lstm_ae_config.pkl"
) -> Tuple[LSTMAutoencoder, PerStationScaler, Dict[str, float]]:
    print("Fitting Per-Station Scaler...", flush=True)
    scaler = PerStationScaler()
    scaler.fit(train_history)

    print("Building sliding windows with disaster oversampling...", flush=True)
    train_windows, train_sids = build_sliding_windows(train_history, scaler, oversample_extreme=True, step=2)
    val_windows, val_sids = build_sliding_windows(val_history, scaler, oversample_extreme=False, step=2)

    print(f"Train windows shape: {train_windows.shape}, Val windows shape: {val_windows.shape}", flush=True)

    train_ds = WindowDataset(train_windows)
    val_ds = WindowDataset(val_windows)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    model = LSTMAutoencoder(input_dim=INPUT_DIM, hidden_dim=32, num_layers=1)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()

    print(f"Training LSTM-Autoencoder ({epochs} epochs)...", flush=True)

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        for x, y in train_loader:
            optimizer.zero_grad()
            rec = model(x)
            loss = criterion(rec, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(x)
        train_loss /= len(train_ds)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for x, y in val_loader:
                rec = model(x)
                loss = criterion(rec, y)
                val_loss += loss.item() * len(x)
        val_loss /= len(val_ds)

        print(f"  Epoch {epoch:2d}/{epochs:2d} | Train MSE: {train_loss:.6f} | Val MSE: {val_loss:.6f}", flush=True)

    # Compute Per-Station K-Sigma Thresholds on Validation Split
    print("Computing Per-Station K-Sigma Thresholds on Validation Split...", flush=True)
    model.eval()
    station_val_errors: Dict[str, List[float]] = {sid: [] for sid in STATION_IDS}

    val_windows_no_os, val_sids_no_os = build_sliding_windows(val_history, scaler, oversample_extreme=False)
    with torch.no_grad():
        for w, sid in zip(val_windows_no_os, val_sids_no_os):
            x_t = torch.from_numpy(w).unsqueeze(0)
            y_t = x_t[:, :, :NUM_FEATURES]
            rec = model(x_t)
            mse = torch.mean((rec - y_t) ** 2).item()
            station_val_errors[sid].append(mse)

    per_station_thresholds = {}
    print("\nPer-Station Reconstruction Error Thresholds (Val Split):")
    for sid in STATION_IDS:
        errs = np.array(station_val_errors[sid])
        if len(errs) > 0:
            mu = float(np.mean(errs))
            sigma = float(np.std(errs))
            thresh = mu + 3.5 * sigma
            per_station_thresholds[sid] = float(max(thresh, 0.005))
            print(f"  - {sid:<18s}: mean={mu:.6f}, std={sigma:.6f} -> threshold={per_station_thresholds[sid]:.6f}")
        else:
            per_station_thresholds[sid] = 0.02

    # Save Model & Config
    os.makedirs(os.path.dirname(model_save_path), exist_ok=True)
    torch.save(model.state_dict(), model_save_path)

    config = {
        "scaler": scaler,
        "thresholds": per_station_thresholds,
        "window_size": WINDOW_SIZE,
        "input_dim": INPUT_DIM,
        "hidden_dim": 32,
    }
    with open(config_save_path, "wb") as f:
        pickle.dump(config, f)

    print(f"Saved PyTorch model to {model_save_path} and config to {config_save_path}.", flush=True)
    return model, scaler, per_station_thresholds


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from data_loader import load_delhi_12m_history, get_train_val_test_splits

    print("Loading 12-Month Delhi AWS Station Dataset...", flush=True)
    history_12m = load_delhi_12m_history(force_fetch=False)
    train_dict, val_dict, test_dict = get_train_val_test_splits(history_12m)

    model, scaler, thresholds = train_lstm_autoencoder(
        train_history=train_dict,
        val_history=val_dict,
        epochs=15,
        batch_size=128,
        lr=0.001
    )
