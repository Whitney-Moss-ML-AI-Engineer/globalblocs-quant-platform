"""Cross-sectional multi-factor model and composite score.

Inputs: a dict of OHLCV frames per symbol (prices) and an optional fundamentals
frame indexed by symbol. Factors whose inputs are missing are skipped, and the
confidence estimate falls with factor coverage."""
from __future__ import annotations

import numpy as np
import pandas as pd

# sign: +1 means "higher raw value is better"
FACTOR_DEFS: dict[str, list[tuple[str, int]]] = {
    "value": [("earnings_yield", 1), ("book_to_price", 1), ("fcf_yield", 1), ("ev_ebitda", -1)],
    "momentum": [("mom_12_1", 1), ("mom_6", 1)],
    "quality": [("roe", 1), ("roic", 1), ("debt_to_equity", -1), ("accruals", -1)],
    "growth": [("revenue_growth", 1), ("earnings_growth", 1)],
    "low_volatility": [("vol_63", -1)],
    "size": [("log_mcap", -1)],
    "liquidity": [("log_adv", 1)],
    "dividend_yield": [("dividend_yield", 1)],
    "earnings_revisions": [("eps_revision_3m", 1)],
    "profitability": [("operating_margin", 1), ("profit_margin", 1)],
    "investment_efficiency": [("asset_growth", -1)],
    "market_beta": [("beta", -1)],
}

DEFAULT_WEIGHTS = {"value": 0.12, "momentum": 0.14, "quality": 0.12, "growth": 0.10, "low_volatility": 0.08,
                   "size": 0.04, "liquidity": 0.06, "dividend_yield": 0.05, "earnings_revisions": 0.08,
                   "profitability": 0.09, "investment_efficiency": 0.06, "market_beta": 0.06}


def price_features(prices: dict[str, pd.DataFrame], bench: pd.Series | None = None) -> pd.DataFrame:
    rows = {}
    for sym, df in prices.items():
        c = df["close"].dropna()
        r = c.pct_change().dropna()
        f = {
            "mom_12_1": c.iloc[-1 - 21] / c.iloc[-1 - 252] - 1 if len(c) > 253 else np.nan,  # skip last month
            "mom_6": c.iloc[-1] / c.iloc[-127] - 1 if len(c) > 127 else np.nan,
            "vol_63": r.tail(63).std() * np.sqrt(252) if len(r) >= 63 else np.nan,
            "log_adv": np.log((df["close"] * df["volume"]).tail(20).mean() + 1),
        }
        if bench is not None:
            br = bench.pct_change().reindex(r.index).dropna()
            jr = r.reindex(br.index).tail(252)
            br = br.tail(252)
            f["beta"] = np.cov(jr, br)[0, 1] / np.var(br, ddof=1) if len(br) > 60 else np.nan
        rows[sym] = f
    return pd.DataFrame.from_dict(rows, orient="index")


def _zscore(x: pd.Series, clip: float = 3.0) -> pd.Series:
    x = x.astype(float)
    lo, hi = x.quantile(0.01), x.quantile(0.99)
    x = x.clip(lo, hi)  # winsorize
    sd = x.std(ddof=0)
    if not np.isfinite(sd) or sd == 0:
        return x * 0
    return ((x - x.mean()) / sd).clip(-clip, clip)


def factor_scores(raw: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for factor, comps in FACTOR_DEFS.items():
        parts = [sign * _zscore(raw[col]) for col, sign in comps if col in raw and raw[col].notna().sum() >= 3]
        if parts:
            out[factor] = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    return pd.DataFrame(out, index=raw.index)


def composite(prices: dict[str, pd.DataFrame], fundamentals: pd.DataFrame | None = None,
              bench: pd.Series | None = None, weights: dict[str, float] | None = None) -> pd.DataFrame:
    raw = price_features(prices, bench)
    if fundamentals is not None and not fundamentals.empty:
        f = fundamentals.copy()
        if "pe" in f:
            f["earnings_yield"] = 1 / f["pe"].where(f["pe"] > 0)
        if "pb" in f:
            f["book_to_price"] = 1 / f["pb"].where(f["pb"] > 0)
        if "market_cap" in f:
            f["log_mcap"] = np.log(f["market_cap"])
        raw = raw.join(f, how="left", rsuffix="_f")
    scores = factor_scores(raw)
    w = pd.Series(weights or DEFAULT_WEIGHTS).reindex(scores.columns).fillna(0)
    avail = scores.notna().astype(float).mul(w, axis=1)
    comp = scores.fillna(0).mul(w, axis=1).sum(axis=1) / avail.sum(axis=1).replace(0, np.nan)
    coverage = avail.sum(axis=1) / w.sum()
    agreement = (np.sign(scores).eq(np.sign(comp), axis=0)).sum(axis=1) / scores.notna().sum(axis=1).replace(0, np.nan)
    out = scores.copy()
    out["composite"] = comp
    out["percentile"] = comp.rank(pct=True) * 100
    out["rank"] = comp.rank(ascending=False, method="min").astype("Int64")
    out["confidence"] = (0.6 * coverage + 0.4 * agreement.fillna(0)).clip(0, 1).round(3)
    return out.sort_values("composite", ascending=False)
