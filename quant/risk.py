"""Performance and risk analytics."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

TD = 252


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1


def var_cvar(r: pd.Series, level: float = 0.95) -> dict:
    r = r.dropna()
    q = np.quantile(r, 1 - level)
    z = stats.norm.ppf(1 - level)
    return {"var_hist": float(-q), "cvar_hist": float(-r[r <= q].mean()),
            "var_param": float(-(r.mean() + z * r.std(ddof=1))),
            "cvar_param": float(-(r.mean() - r.std(ddof=1) * stats.norm.pdf(z) / (1 - level)))}


def metrics(r: pd.Series, bench: pd.Series | None = None, rf: float = 0.0, level: float = 0.95) -> dict:
    r = r.dropna()
    ex = r - rf / TD
    eq = (1 + r).cumprod()
    years = len(r) / TD
    downside = ex[ex < 0].std(ddof=1) * np.sqrt(TD)
    out = {
        "total_return": float(eq.iloc[-1] - 1),
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1) if years > 0 else np.nan,
        "volatility": float(r.std(ddof=1) * np.sqrt(TD)),
        "sharpe": float(ex.mean() / r.std(ddof=1) * np.sqrt(TD)) if r.std() > 0 else np.nan,
        "sortino": float(ex.mean() * TD / downside) if downside > 0 else np.nan,
        "max_drawdown": float(drawdown(eq).min()),
        **var_cvar(r, level),
    }
    out["calmar"] = out["cagr"] / abs(out["max_drawdown"]) if out["max_drawdown"] < 0 else np.nan
    if bench is not None:
        b = bench.reindex(r.index).dropna()
        rr = r.reindex(b.index)
        beta = float(np.cov(rr, b)[0, 1] / np.var(b, ddof=1))
        active = rr - b
        te = float(active.std(ddof=1) * np.sqrt(TD))
        out.update(beta=beta, alpha=float((rr.mean() - rf / TD - beta * (b.mean() - rf / TD)) * TD),
                   correlation=float(rr.corr(b)), tracking_error=te,
                   information_ratio=float(active.mean() * TD / te) if te > 0 else np.nan)
    return {k: (None if isinstance(v, float) and not np.isfinite(v) else round(v, 6)) for k, v in out.items()}


def portfolio_risk(weights: pd.Series, returns: pd.DataFrame, sectors: dict[str, str] | None = None) -> dict:
    w = weights.reindex(returns.columns).fillna(0)
    pr = returns @ w
    cov = returns.cov() * TD
    pv = float(np.sqrt(w @ cov @ w))
    mrc = (cov @ w) / pv
    out = {"portfolio_volatility": pv, "risk_contribution": (w * mrc / pv).round(4).to_dict(),
           "hhi_concentration": float((w ** 2).sum()), "effective_n": float(1 / (w ** 2).sum()),
           "largest_position": float(w.max()), "correlation": returns.corr().round(3).to_dict(), **var_cvar(pr)}
    if sectors:
        out["sector_exposure"] = w.groupby(pd.Series(sectors).reindex(w.index).fillna("Unknown")).sum().round(4).to_dict()
    return out


def position_size(equity: float, entry: float, stop: float, risk_per_trade: float = 0.01,
                  max_position_pct: float = 0.10) -> dict:
    """Fixed-fractional sizing capped by a maximum position percentage."""
    per_share = abs(entry - stop)
    if per_share <= 0:
        raise ValueError("stop must differ from entry")
    by_risk = np.floor(equity * risk_per_trade / per_share)
    by_cap = np.floor(equity * max_position_pct / entry)
    shares = int(max(0, min(by_risk, by_cap)))
    return {"shares": shares, "dollar_risk": round(shares * per_share, 2), "position_value": round(shares * entry, 2),
            "binding_constraint": "risk_per_trade" if by_risk <= by_cap else "max_position_pct"}
