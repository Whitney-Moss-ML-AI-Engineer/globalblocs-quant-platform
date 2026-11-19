"""Deep-learning forecasters (PyTorch): ANN, 1-D CNN, LSTM, GRU, BiLSTM, TCN, Transformer.
PyTorch is imported lazily so the rest of the platform runs without it.
Training uses a chronological split; scaling statistics come from the training window only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _torch():
    import torch
    from torch import nn
    return torch, nn


def build(kind: str, n_features: int, window: int, hidden: int = 64):
    torch, nn = _torch()

    class Seq(nn.Module):
        def __init__(self):
            super().__init__()
            if kind in ("lstm", "gru", "bilstm"):
                rnn = nn.GRU if kind == "gru" else nn.LSTM
                self.body = rnn(n_features, hidden, num_layers=2, batch_first=True, dropout=0.1,
                                bidirectional=kind == "bilstm")
                self.head = nn.Linear(hidden * (2 if kind == "bilstm" else 1), 1)
            elif kind in ("cnn", "tcn"):
                dil = [1, 2, 4] if kind == "tcn" else [1, 1, 1]
                layers, ch = [], n_features
                for dl in dil:
                    layers += [nn.Conv1d(ch, hidden, 3, padding=2 * dl, dilation=dl), nn.ReLU()]
                    ch = hidden
                self.body = nn.Sequential(*layers)
                self.head = nn.Linear(hidden, 1)
            elif kind == "transformer":
                self.proj = nn.Linear(n_features, hidden)
                self.pos = nn.Parameter(torch.zeros(1, window, hidden))
                enc = nn.TransformerEncoderLayer(hidden, 4, hidden * 2, dropout=0.1, batch_first=True)
                self.body = nn.TransformerEncoder(enc, 2)
                self.head = nn.Linear(hidden, 1)
            else:  # ann
                self.body = nn.Sequential(nn.Flatten(), nn.Linear(n_features * window, hidden), nn.ReLU(),
                                          nn.Dropout(0.1), nn.Linear(hidden, hidden), nn.ReLU())
                self.head = nn.Linear(hidden, 1)

        def forward(self, x):  # x: (batch, window, features)
            if kind in ("lstm", "gru", "bilstm"):
                out, _ = self.body(x)
                return self.head(out[:, -1])
            if kind in ("cnn", "tcn"):
                out = self.body(x.transpose(1, 2))[..., : x.shape[1]]  # trim so convolution stays causal
                return self.head(out[..., -1])
            if kind == "transformer":
                out = self.body(self.proj(x) + self.pos)
                return self.head(out[:, -1])
            return self.head(self.body(x))
    return Seq()


def windows(X: np.ndarray, y: np.ndarray, w: int):
    xs = np.stack([X[i - w:i] for i in range(w, len(X) + 1)])
    return xs, y[w - 1:]


def train_forecaster(X: pd.DataFrame, y: pd.Series, kind: str = "lstm", window: int = 30, epochs: int = 20,
                     lr: float = 1e-3, train_frac: float = 0.8, seed: int = 7) -> dict:
    torch, nn = _torch()
    torch.manual_seed(seed)
    cut = int(len(X) * train_frac)
    mu, sd = X.iloc[:cut].mean(), X.iloc[:cut].std().replace(0, 1)
    Xs = ((X - mu) / sd).values.astype("float32")
    xs, ys = windows(Xs, y.values.astype("float32"), window)
    split = cut - window + 1
    xtr, ytr = torch.tensor(xs[:split]), torch.tensor(ys[:split]).unsqueeze(1)
    xte, yte = torch.tensor(xs[split:]), torch.tensor(ys[split:]).unsqueeze(1)
    model = build(kind, X.shape[1], window)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()
    for _ in range(epochs):
        model.train()
        for i in range(0, len(xtr), 64):
            opt.zero_grad()
            loss = loss_fn(model(xtr[i:i + 64]), ytr[i:i + 64])
            loss.backward()
            opt.step()
    model.eval()
    with torch.no_grad():
        p = model(xte).squeeze(1).numpy()
    t = yte.squeeze(1).numpy()
    return {"model": kind, "test_size": len(t), "directional_accuracy": float((np.sign(p) == np.sign(t)).mean()),
            "rmse": float(np.sqrt(((p - t) ** 2).mean())), "ensemble_member": True}


def ensemble(X, y, kinds=("lstm", "gru", "tcn", "transformer"), **kw) -> list[dict]:
    return [train_forecaster(X, y, k, **kw) for k in kinds]
