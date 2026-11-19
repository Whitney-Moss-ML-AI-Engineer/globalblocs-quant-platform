"""Machine-learning prediction pipeline with leakage controls.

* Features use data through bar t only; target is the forward h-bar return, so the last h rows
  are dropped and TimeSeriesSplit uses gap=h (purging) between train and test.
* Evaluation: walk-forward out-of-sample predictions, directional accuracy with a binomial test
  against 50%, bootstrap CI, information coefficient, permutation feature importance, PSI drift.
* Optional libraries (xgboost, lightgbm, catboost, shap) are used when installed."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import BayesianRidge, ElasticNet, Lasso, LinearRegression, Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

from quant import indicators as ind


def model_zoo() -> dict:
    z = {
        "linear": LinearRegression(), "ridge": Ridge(alpha=1.0), "lasso": Lasso(alpha=1e-4, max_iter=5000),
        "elastic_net": ElasticNet(alpha=1e-4, l1_ratio=0.5, max_iter=5000),
        "random_forest": RandomForestRegressor(n_estimators=200, max_depth=5, min_samples_leaf=20, n_jobs=-1, random_state=7),
        "gradient_boosting": GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=7),
        "svm": SVR(C=0.5, epsilon=0.001), "knn": KNeighborsRegressor(n_neighbors=25), "bayesian_ridge": BayesianRidge(),
    }
    try:
        from xgboost import XGBRegressor
        z["xgboost"] = XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=7)
    except ImportError:
        pass
    try:
        from lightgbm import LGBMRegressor
        z["lightgbm"] = LGBMRegressor(n_estimators=200, num_leaves=15, learning_rate=0.05, random_state=7, verbose=-1)
    except ImportError:
        pass
    try:
        from catboost import CatBoostRegressor
        z["catboost"] = CatBoostRegressor(iterations=200, depth=4, verbose=0, random_seed=7)
    except ImportError:
        pass
    return {k: make_pipeline(StandardScaler(), v) for k, v in z.items()}


FEATURES = ["ret_1", "mom_20", "vol_20", "rsi_14", "macd_hist", "bb_pctb", "bb_width", "adx", "stoch_k",
            "rvol_20", "dist_sma50", "dist_sma200", "ret_5", "ret_lag1", "ret_lag2", "atr_pct"]


def build_dataset(df: pd.DataFrame, horizon: int = 5) -> tuple[pd.DataFrame, pd.Series]:
    d = ind.add_all(df)
    d["dist_sma50"] = d["close"] / d["sma_50"] - 1
    d["dist_sma200"] = d["close"] / d["sma_200"] - 1
    d["ret_5"] = d["close"].pct_change(5)
    d["ret_lag1"], d["ret_lag2"] = d["ret_1"].shift(1), d["ret_1"].shift(2)
    d["atr_pct"] = d["atr_14"] / d["close"]
    y = d["close"].shift(-horizon) / d["close"] - 1   # forward return: the label
    data = d[FEATURES].assign(y=y).replace([np.inf, -np.inf], np.nan).dropna()
    return data[FEATURES], data["y"]


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index; > 0.25 usually signals material drift."""
    qs = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    e = np.histogram(expected, qs)[0] / len(expected) + 1e-6
    a = np.histogram(np.clip(actual, qs[0], qs[-1]), qs)[0] / len(actual) + 1e-6
    return float(((a - e) * np.log(a / e)).sum())


def walk_forward(df: pd.DataFrame, models: list[str] | None = None, horizon: int = 5, splits: int = 5,
                 n_boot: int = 500, seed: int = 7) -> dict:
    X, y = build_dataset(df, horizon)
    zoo = model_zoo()
    names = models or ["ridge", "random_forest", "gradient_boosting"]
    tss = TimeSeriesSplit(n_splits=splits, gap=horizon)
    rng = np.random.default_rng(seed)
    results = {}
    for name in names:
        preds = pd.Series(np.nan, index=y.index)
        for tr, te in tss.split(X):
            m = zoo[name]
            m.fit(X.iloc[tr], y.iloc[tr])
            preds.iloc[te] = m.predict(X.iloc[te])
        mask = preds.notna()
        p, t = preds[mask], y[mask]
        hits = int((np.sign(p) == np.sign(t)).sum())
        n = int(mask.sum())
        boot = [np.mean((np.sign(p.values[ix]) == np.sign(t.values[ix]))) for ix in rng.integers(0, n, (n_boot, n))]
        ic = stats.spearmanr(p, t).statistic
        # Overlapping h-bar labels are not independent: test on the effective sample n/h, and against
        # the naive "always predict the majority direction" baseline rather than a coin flip.
        base = max((t > 0).mean(), (t <= 0).mean())
        n_eff = max(1, n // horizon)
        k_eff = int(round(hits / n * n_eff))
        results[name] = {
            "oos_observations": n, "effective_independent_obs": n_eff, "directional_accuracy": hits / n,
            "naive_baseline_accuracy": float(base), "edge_vs_baseline": float(hits / n - base),
            "accuracy_95ci": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
            "binomial_p_value_vs_baseline": float(stats.binomtest(k_eff, n_eff, min(base, 0.999), alternative="greater").pvalue),
            "information_coefficient": float(ic), "mae": float((p - t).abs().mean()),
            "rmse": float(np.sqrt(((p - t) ** 2).mean())),
            "latest_prediction": float(zoo[name].predict(X.iloc[[-1]])[0]),
        }
    best = max(results, key=lambda k: results[k]["information_coefficient"])
    final = zoo[best].fit(X, y)
    cut = int(len(X) * 0.8)
    pi = permutation_importance(final, X.iloc[cut:], y.iloc[cut:], n_repeats=5, random_state=seed)
    drift = {c: round(psi(X[c].values[:cut], X[c].values[cut:]), 4) for c in FEATURES}
    iso = IsolationForest(random_state=seed).fit(X.iloc[:cut])
    return {
        "horizon_bars": horizon, "models": results, "best_model_by_ic": best,
        "feature_importance": dict(sorted(zip(FEATURES, pi.importances_mean.round(6)), key=lambda kv: -kv[1])),
        "feature_drift_psi": drift, "recent_anomaly_rate": float((iso.predict(X.iloc[cut:]) == -1).mean()),
        "note": "Out-of-sample estimates only; past predictive accuracy does not guarantee future results.",
    }


def save_model(model, meta: dict, folder: str = "models") -> str:
    """Versioned model registry: artifact + metadata with content hash."""
    import joblib
    Path(folder).mkdir(parents=True, exist_ok=True)
    version = time.strftime("%Y%m%d-%H%M%S")
    path = Path(folder) / f"{meta.get('name', 'model')}-{version}.joblib"
    joblib.dump(model, path)
    meta = {**meta, "version": version, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=str))
    return str(path)
