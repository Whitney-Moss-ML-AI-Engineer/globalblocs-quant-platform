"""Trading-signal generation. Each signal carries every field the spec requires and an
explicit disclaimer; nothing here is a guaranteed return."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from quant import indicators as ind

DISCLAIMER = ("Model-generated research signal, not investment advice or a guaranteed return. "
              "Verify price, liquidity and risk before any trade.")
STRATEGIES = ["momentum", "breakout", "mean_reversion", "trend_following", "vwap", "gap_and_go", "pullback"]
HOLDING = {"momentum": "1-5 days", "breakout": "1-10 days", "mean_reversion": "1-3 days",
           "trend_following": "2-8 weeks", "vwap": "intraday", "gap_and_go": "intraday", "pullback": "3-10 days"}


def _classify(score: float) -> str:
    if score >= 0.75: return "Strong Buy Candidate"
    if score >= 0.55: return "Buy Candidate"
    if score >= 0.40: return "Watch"
    if score > -0.40: return "Neutral"
    if score > -0.70: return "Sell Candidate"
    return "Avoid"


def _conditions(strategy: str, x: pd.Series, prev: pd.Series) -> list[tuple[str, bool, float]]:
    """(description, met, weight); bearish conditions have negative weight."""
    c = x["close"]
    common = [("Price above 50-day SMA", c > x["sma_50"], 0.10), ("ADX > 20 (trend present)", x["adx"] > 20, 0.05),
              ("Relative volume > 1.5", x["rvol_20"] > 1.5, 0.10)]
    s = {
        "momentum": [("20-day momentum > 5%", x["mom_20"] > 0.05, 0.30), ("MACD above signal", x["macd"] > x["macd_signal"], 0.25),
                     ("RSI 50-75", 50 <= x["rsi_14"] <= 75, 0.20), ("RSI > 80 (overextended)", x["rsi_14"] > 80, -0.30)],
        "breakout": [("Close above prior 20-bar resistance", c > x["resistance"], 0.45), ("Bollinger %B > 1", x["bb_pctb"] > 1, 0.15),
                     ("MACD histogram rising", x["macd_hist"] > prev["macd_hist"], 0.15), ("Close below support", c < x["support"], -0.6)],
        "mean_reversion": [("RSI < 30", x["rsi_14"] < 30, 0.35), ("Below lower Bollinger band", c < x["bb_lower"], 0.30),
                           ("Stochastic %K < 20", x["stoch_k"] < 20, 0.15), ("RSI > 70", x["rsi_14"] > 70, -0.5)],
        "trend_following": [("SMA50 > SMA200", x["sma_50"] > x["sma_200"], 0.35), ("+DI > -DI", x["plus_di"] > x["minus_di"], 0.20),
                            ("EMA9 > EMA21", x["ema_9"] > x["ema_21"], 0.20), ("SMA50 < SMA200", x["sma_50"] < x["sma_200"], -0.5)],
        "vwap": [("Crossed above VWAP", (c > x["vwap"]) and (prev["close"] <= prev["vwap"]), 0.45), ("Above VWAP", c > x["vwap"], 0.20),
                 ("Below VWAP", c < x["vwap"], -0.4)],
        "gap_and_go": [("Gap up > 2%", x["open"] / prev["close"] - 1 > 0.02, 0.40), ("Holding above open", c > x["open"], 0.25),
                       ("Gap down > 2%", x["open"] / prev["close"] - 1 < -0.02, -0.5)],
        "pullback": [("Uptrend (EMA21 > SMA50)", x["ema_21"] > x["sma_50"], 0.30), ("Pulled back to EMA21 (within 1 ATR)",
                     abs(c - x["ema_21"]) < x["atr_14"], 0.30), ("RSI 40-55", 40 <= x["rsi_14"] <= 55, 0.15)],
    }[strategy]
    return s + common


def generate_signal(symbol: str, df: pd.DataFrame, strategy: str = "momentum", rr_targets=(1.0, 2.0, 3.0),
                    atr_stop_mult: float = 1.5, valid_bars: int = 3) -> dict:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy}; choose from {STRATEGIES}")
    data = ind.add_all(df).dropna(subset=["sma_50", "atr_14", "macd_signal", "adx"])
    if len(data) < 2:
        raise ValueError("not enough history (need ~60+ bars)")
    x, prev = data.iloc[-1], data.iloc[-2]
    conds = _conditions(strategy, x, prev)
    pos = sum(w for _, m, w in conds if w > 0)
    score = sum(w for _, m, w in conds if bool(m)) / pos
    score = float(np.clip(score, -1, 1))
    price, a = float(x["close"]), float(x["atr_14"])
    entry_lo, entry_hi = price - 0.25 * a, price + 0.10 * a
    stop = price - atr_stop_mult * a
    risk = price - stop
    targets = [round(price + r * risk, 4) for r in rr_targets]
    ts = data.index[-1]
    return {
        "symbol": symbol, "strategy": strategy, "classification": _classify(score),
        "price": round(price, 4), "price_timestamp": str(ts),
        "data_source": df.attrs.get("source", "unknown"), "data_latency": df.attrs.get("latency", "unknown"),
        "entry_zone": [round(entry_lo, 4), round(entry_hi, 4)], "stop_loss": round(stop, 4),
        "profit_targets": targets, "risk_reward": [round((t - price) / risk, 2) for t in targets],
        "expected_holding_period": HOLDING[strategy], "volume": float(x["volume"]),
        "relative_volume": None if pd.isna(x["rvol_20"]) else round(float(x["rvol_20"]), 2),
        "volatility_annualized": None if pd.isna(x["vol_20"]) else round(float(x["vol_20"]), 4), "atr": round(a, 4),
        "supporting_indicators": [d for d, m, w in conds if bool(m) and w > 0],
        "contrary_indicators": [d for d, m, w in conds if bool(m) and w < 0],
        "market_conditions": "trending" if x["adx"] > 25 else "range-bound",
        "score": round(score, 3), "confidence": round(abs(score) * min(1.0, len(data) / 252), 3),
        "invalidation": f"Close below {round(stop, 2)} or signal older than {valid_bars} bars after {ts}",
        "generated_at": datetime.now(timezone.utc).isoformat(), "disclaimer": DISCLAIMER,
    }


def best_signals(prices: dict[str, pd.DataFrame], strategies=None, top: int = 25) -> list[dict]:
    out = []
    for sym, df in prices.items():
        for st in strategies or STRATEGIES:
            try:
                out.append(generate_signal(sym, df, st))
            except ValueError:
                continue
    return sorted(out, key=lambda s: s["score"], reverse=True)[:top]


def pairs_zscore(a: pd.Series, b: pd.Series, n: int = 60) -> pd.DataFrame:
    """Statistical-arbitrage spread: rolling OLS hedge ratio (estimated on data through t-1)."""
    la, lb = np.log(a), np.log(b)
    beta = (la.rolling(n).cov(lb) / lb.rolling(n).var()).shift(1)
    spread = la - beta * lb
    z = (spread - spread.rolling(n).mean()) / spread.rolling(n).std()
    sig = pd.Series(np.where(z > 2, "short spread", np.where(z < -2, "long spread", "neutral")), index=z.index)
    return pd.DataFrame({"hedge_ratio": beta, "spread": spread, "zscore": z, "signal": sig})
