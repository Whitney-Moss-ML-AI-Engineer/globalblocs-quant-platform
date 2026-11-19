"""Market, macro and filings data providers.

Every frame returned carries df.attrs['source'] and df.attrs['latency'] so the UI can label
real-time vs delayed vs simulated data and show the source and timestamp of every price."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


def _tag(df: pd.DataFrame, source: str, latency: str) -> pd.DataFrame:
    df.attrs.update(source=source, latency=latency, retrieved_at=datetime.now(timezone.utc).isoformat())
    return df


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Basic data-quality gate: required columns, sorted unique index, no non-positive prices,
    high >= low. Raises on failure so bad data never reaches a model."""
    need = {"open", "high", "low", "close", "volume"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"missing columns {missing}")
    df = df[~df.index.duplicated()].sort_index()
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("non-positive prices")
    if (df["high"] < df["low"]).any():
        raise ValueError("high < low")
    return df


class SyntheticProvider:
    """Deterministic simulated prices for demos, tests and offline use. Always labeled SIMULATED."""
    name = "synthetic"

    def history(self, symbol: str, days: int = 600, end: str | None = None) -> pd.DataFrame:
        seed = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        idx = pd.bdate_range(end=end or "2026-11-17", periods=days)
        mu, sig = rng.uniform(-0.0002, 0.0009), rng.uniform(0.012, 0.03)
        r = rng.normal(mu, sig, days)
        close = 20 + rng.uniform(0, 300) * np.exp(np.cumsum(r)) / np.exp(r[0])
        op = close * (1 + rng.normal(0, sig / 3, days))
        hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, sig / 2, days)))
        lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, sig / 2, days)))
        vol = rng.lognormal(14, 0.4, days).round()
        df = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close, "volume": vol}, index=idx)
        return _tag(validate_ohlcv(df), "SIMULATED (synthetic generator)", "simulated")


class CSVProvider:
    name = "csv"

    def __init__(self, folder: str):
        self.folder = Path(folder)

    def history(self, symbol: str, **_) -> pd.DataFrame:
        df = pd.read_csv(self.folder / f"{symbol}.csv", parse_dates=[0], index_col=0)
        df.columns = [c.lower() for c in df.columns]
        return _tag(validate_ohlcv(df), f"CSV {self.folder}", "end-of-day")


class PolygonProvider:
    """Polygon.io aggregates. Latency depends on your plan: set POLYGON_REALTIME=true only if licensed."""
    name = "polygon"

    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.environ["POLYGON_API_KEY"]
        self.latency = "real-time" if os.getenv("POLYGON_REALTIME", "false").lower() == "true" else "delayed-15m"

    def history(self, symbol: str, days: int = 600, timespan: str = "day", **_) -> pd.DataFrame:
        end = pd.Timestamp.utcnow().normalize()
        start = end - pd.Timedelta(days=int(days * 1.5))
        url = (f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/{timespan}/"
               f"{start:%Y-%m-%d}/{end:%Y-%m-%d}")
        js = httpx.get(url, params={"adjusted": "true", "limit": 50000, "apiKey": self.key}, timeout=30).json()
        df = pd.DataFrame(js.get("results", []))
        if df.empty:
            raise ValueError(f"no data for {symbol}")
        df.index = pd.to_datetime(df["t"], unit="ms")
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        return _tag(validate_ohlcv(df[["open", "high", "low", "close", "volume"]]), "Polygon.io", self.latency)


class FREDClient:
    """Federal Reserve Economic Data (rates, Treasury yields, CPI, payrolls)."""
    SERIES = {"fed_funds": "FEDFUNDS", "ust_10y": "DGS10", "ust_2y": "DGS2", "cpi": "CPIAUCSL",
              "unemployment": "UNRATE", "payrolls": "PAYEMS", "wti": "DCOILWTICO", "usd_index": "DTWEXBGS"}

    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.environ["FRED_API_KEY"]

    def series(self, series_id: str) -> pd.Series:
        js = httpx.get("https://api.stlouisfed.org/fred/series/observations",
                       params={"series_id": series_id, "api_key": self.key, "file_type": "json"}, timeout=30).json()
        s = pd.Series({pd.Timestamp(o["date"]): pd.to_numeric(o["value"], errors="coerce") for o in js["observations"]})
        s.attrs.update(source=f"FRED {series_id}", latency="as-published")
        return s


class SECEdgarClient:
    """SEC EDGAR XBRL company facts and filings index. SEC requires a descriptive User-Agent."""

    def __init__(self, user_agent: str | None = None):
        self.headers = {"User-Agent": user_agent or os.getenv("SEC_USER_AGENT", "GlobalBLOCS research admin@example.com")}

    def company_facts(self, cik: int) -> dict:
        return httpx.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=self.headers, timeout=30).json()

    def submissions(self, cik: int) -> dict:
        return httpx.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=self.headers, timeout=30).json()


def get_provider(name: str | None = None):
    name = (name or os.getenv("MARKET_DATA_PROVIDER", "synthetic")).lower()
    if name == "polygon":
        return PolygonProvider()
    if name == "csv":
        return CSVProvider(os.getenv("CSV_DATA_DIR", "./data/csv"))
    return SyntheticProvider()
