"""Portfolio construction: equal weight, mean-variance, minimum variance, maximum Sharpe,
risk parity, hierarchical risk parity (Lopez de Prado), maximum diversification,
Black-Litterman, beta-adjusted and factor-weighted. Long-only with per-asset caps."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform

TRADING_DAYS = 252


def _solve(obj, n, max_w=1.0, extra=()):
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}, *extra]
    res = minimize(obj, np.full(n, 1 / n), bounds=[(0, max_w)] * n, constraints=cons, method="SLSQP",
                   options={"maxiter": 500, "ftol": 1e-12})
    w = np.clip(res.x, 0, None)
    return w / w.sum()


def estimates(returns: pd.DataFrame, shrink: float = 0.1):
    mu = returns.mean() * TRADING_DAYS
    cov = returns.cov() * TRADING_DAYS
    target = np.diag(np.diag(cov))  # shrink toward diagonal for stability
    return mu, pd.DataFrame((1 - shrink) * cov.values + shrink * target, cov.index, cov.columns)


def equal_weight(cols) -> pd.Series:
    return pd.Series(1 / len(cols), index=cols)


def min_variance(cov: pd.DataFrame, max_w=1.0) -> pd.Series:
    S = cov.values
    return pd.Series(_solve(lambda w: w @ S @ w, len(S), max_w), cov.index)


def mean_variance(mu: pd.Series, cov: pd.DataFrame, risk_aversion=3.0, max_w=1.0) -> pd.Series:
    S, m = cov.values, mu.values
    return pd.Series(_solve(lambda w: -(w @ m - 0.5 * risk_aversion * w @ S @ w), len(m), max_w), cov.index)


def max_sharpe(mu: pd.Series, cov: pd.DataFrame, rf=0.0, max_w=1.0) -> pd.Series:
    S, m = cov.values, mu.values
    return pd.Series(_solve(lambda w: -(w @ m - rf) / np.sqrt(w @ S @ w + 1e-12), len(m), max_w), cov.index)


def risk_parity(cov: pd.DataFrame, max_w=1.0) -> pd.Series:
    S = cov.values
    n = len(S)

    def obj(w):
        pv = w @ S @ w
        rc = w * (S @ w) / pv
        return ((rc - 1 / n) ** 2).sum()
    return pd.Series(_solve(obj, n, max_w), cov.index)


def max_diversification(cov: pd.DataFrame, max_w=1.0) -> pd.Series:
    S = cov.values
    vol = np.sqrt(np.diag(S))
    return pd.Series(_solve(lambda w: -(w @ vol) / np.sqrt(w @ S @ w), len(S), max_w), cov.index)


def hrp(cov: pd.DataFrame) -> pd.Series:
    sd = np.sqrt(np.diag(cov))
    corr = cov.values / np.outer(sd, sd)
    dist = np.sqrt(np.clip((1 - corr) / 2, 0, None))
    np.fill_diagonal(dist, 0)
    order = leaves_list(linkage(squareform(dist, checks=False), "single"))
    w = pd.Series(1.0, index=order)
    clusters = [list(order)]
    S = cov.values

    def cvar(idx):
        sub = S[np.ix_(idx, idx)]
        iv = 1 / np.diag(sub)
        iv /= iv.sum()
        return iv @ sub @ iv
    while clusters:
        clusters = [c[j:k] for c in clusters for j, k in ((0, len(c) // 2), (len(c) // 2, len(c))) if len(c) > 1]
        for i in range(0, len(clusters), 2):
            a, b = clusters[i], clusters[i + 1]
            va, vb = cvar(a), cvar(b)
            alpha = 1 - va / (va + vb)
            w[a] *= alpha
            w[b] *= 1 - alpha
    w.index = cov.index[w.index]
    return w.reindex(cov.index)


def black_litterman(cov: pd.DataFrame, mkt_weights: pd.Series, P: np.ndarray, Q: np.ndarray,
                    risk_aversion=2.5, tau=0.05, omega: np.ndarray | None = None) -> tuple[pd.Series, pd.Series]:
    """Returns (posterior expected returns, implied optimal weights)."""
    S = cov.values
    pi = risk_aversion * S @ mkt_weights.reindex(cov.index).values
    omega = omega if omega is not None else np.diag(np.diag(P @ (tau * S) @ P.T))
    inv_ts = np.linalg.inv(tau * S)
    post = np.linalg.solve(inv_ts + P.T @ np.linalg.inv(omega) @ P, inv_ts @ pi + P.T @ np.linalg.inv(omega) @ Q)
    mu = pd.Series(post, cov.index)
    return mu, mean_variance(mu, cov, risk_aversion)


def beta_adjusted(betas: pd.Series, target_beta=1.0, max_w=1.0) -> pd.Series:
    n = len(betas)
    b = betas.values
    w = _solve(lambda w: ((w - 1 / n) ** 2).sum(), n, max_w, extra=[{"type": "eq", "fun": lambda w: w @ b - target_beta}])
    return pd.Series(w, betas.index)


def factor_weighted(scores: pd.Series, top_n: int | None = None) -> pd.Series:
    s = scores.dropna().sort_values(ascending=False)
    if top_n:
        s = s.head(top_n)
    s = s - s.min() + 1e-6
    return s / s.sum()


def optimize(returns: pd.DataFrame, method: str = "max_sharpe", max_weight: float = 0.35, rf: float = 0.0, **kw) -> pd.Series:
    mu, cov = estimates(returns)
    m = method.lower()
    if m == "equal_weight": return equal_weight(returns.columns)
    if m == "min_variance": return min_variance(cov, max_weight)
    if m == "mean_variance": return mean_variance(mu, cov, kw.get("risk_aversion", 3.0), max_weight)
    if m == "max_sharpe": return max_sharpe(mu, cov, rf, max_weight)
    if m == "risk_parity": return risk_parity(cov, max_weight)
    if m == "hrp": return hrp(cov)
    if m == "max_diversification": return max_diversification(cov, max_weight)
    raise ValueError(f"unknown method {method}")


def allocate_capital(weights: pd.Series, prices: pd.Series, capital: float, cash_buffer: float = 0.02) -> pd.DataFrame:
    """Whole-share allocation that never exceeds available capital."""
    investable = capital * (1 - cash_buffer)
    shares = np.floor(weights * investable / prices.reindex(weights.index))
    value = shares * prices.reindex(weights.index)
    return pd.DataFrame({"target_weight": weights.round(4), "shares": shares.astype(int), "value": value.round(2),
                         "actual_weight": (value / capital).round(4)})
