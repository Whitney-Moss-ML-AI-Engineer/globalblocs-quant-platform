"""Technical indicators. Every function is causal: the value at bar t uses data
through bar t only, so indicators can be fed to models without look-ahead."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.mask((dn == 0) & up.notna(), 100.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    up, lo = mid + k * sd, mid - k * sd
    return pd.DataFrame({"bb_mid": mid, "bb_upper": up, "bb_lower": lo,
                         "bb_pctb": (close - lo) / (up - lo), "bb_width": (up - lo) / mid})


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = atr(df, n)
    pdi = 100 * pd.Series(plus_dm, df.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    mdi = 100 * pd.Series(minus_dm, df.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"plus_di": pdi, "minus_di": mdi, "adx": dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()})


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    ll = df["low"].rolling(k, min_periods=k).min()
    hh = df["high"].rolling(k, min_periods=k).max()
    pk = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    return pd.DataFrame({"stoch_k": pk, "stoch_d": pk.rolling(d, min_periods=d).mean()})


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP (resets each calendar day). On daily bars this equals the typical price."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = pd.Index(df.index).normalize() if isinstance(df.index, pd.DatetimeIndex) else np.zeros(len(df))
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    return pv / vv.replace(0, np.nan)


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()


def relative_volume(df: pd.DataFrame, n: int = 20) -> pd.Series:
    return df["volume"] / df["volume"].shift(1).rolling(n, min_periods=n).mean()


def relative_strength(close: pd.Series, bench: pd.Series, n: int = 63) -> pd.Series:
    return close.pct_change(n) - bench.reindex(close.index).pct_change(n)


def support_resistance(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Prior-n-bar support/resistance (shifted one bar so a breakout compares to *prior* levels)."""
    return pd.DataFrame({"support": df["low"].rolling(n, min_periods=n).min().shift(1),
                         "resistance": df["high"].rolling(n, min_periods=n).max().shift(1)})


def fibonacci_levels(high: float, low: float) -> dict[str, float]:
    rng = high - low
    return {f"fib_{int(r * 1000) / 10}": high - r * rng for r in (0.236, 0.382, 0.5, 0.618, 0.786)}


def candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    po, pc = o.shift(), c.shift()
    return pd.DataFrame({
        "doji": body / rng < 0.1,
        "hammer": (lower_wick > 2 * body) & (upper_wick < body),
        "shooting_star": (upper_wick > 2 * body) & (lower_wick < body),
        "bull_engulfing": (pc < po) & (c > o) & (c >= po) & (o <= pc),
        "bear_engulfing": (pc > po) & (c < o) & (o >= pc) & (c <= po),
    }, index=df.index)


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of an OHLCV frame with the standard indicator set appended."""
    out = df.copy()
    c = out["close"]
    for n in (10, 20, 50, 200):
        out[f"sma_{n}"] = sma(c, n)
    for n in (9, 21):
        out[f"ema_{n}"] = ema(c, n)
    out["rsi_14"] = rsi(c)
    out = out.join(macd(c)).join(bollinger(c)).join(adx(out)).join(stochastic(out)).join(support_resistance(out))
    out["atr_14"] = atr(out)
    out["vwap"] = vwap(out)
    out["obv"] = obv(out)
    out["rvol_20"] = relative_volume(out)
    out["ret_1"] = c.pct_change()
    out["mom_20"] = c.pct_change(20)
    out["vol_20"] = out["ret_1"].rolling(20).std() * np.sqrt(252)
    out = out.join(candlestick_patterns(out))
    return out
