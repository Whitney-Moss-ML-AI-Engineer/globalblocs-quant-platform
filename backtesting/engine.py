"""Bar-by-bar backtester with realistic frictions.

Decisions use indicator values at the close of bar t-1 and fill at the open of bar t,
which prevents look-ahead. Costs: per-share commission with minimum, half bid/ask spread,
slippage, square-root market impact, and a participation cap on average daily volume.
Stops and targets are checked against the bar's high/low (gap-through fills at the open)."""
from __future__ import annotations

import itertools
import operator
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from quant import indicators as ind
from quant.risk import metrics

OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le}


@dataclass
class Costs:
    commission_per_share: float = 0.0
    min_commission: float = 0.0
    spread_bps: float = 5.0         # full quoted spread; half is paid per side
    slippage_bps: float = 2.0
    impact_coef: float = 0.1        # impact = coef * daily_vol * sqrt(shares / ADV)
    max_participation: float = 0.05  # cap fills at 5% of 20-day ADV


@dataclass
class StrategyConfig:
    name: str = "custom"
    entry_rules: list = field(default_factory=lambda: [{"left": "close", "op": ">", "right": "sma_50"},
                                                       {"left": "rsi_14", "op": "<", "right": 70}])
    exit_rules: list = field(default_factory=lambda: [{"left": "close", "op": "<", "right": "sma_50"}])
    stop_loss_pct: float | None = 0.05
    take_profit_pct: float | None = 0.15
    position_fraction: float = 0.95   # fraction of equity per position
    max_position_value: float | None = None
    allow_short: bool = False         # long-only engine; flag kept for policy checks
    halted_dates: list = field(default_factory=list)


def _rule_mask(df: pd.DataFrame, rules: list) -> pd.Series:
    m = pd.Series(True, index=df.index)
    for r in rules:
        right = df[r["right"]] if isinstance(r["right"], str) else r["right"]
        m &= OPS[r["op"]](df[r["left"]], right).fillna(False)
    return m


def run_backtest(df: pd.DataFrame, cfg: StrategyConfig | None = None, costs: Costs | None = None,
                 initial_capital: float = 100_000.0) -> dict:
    cfg, costs = cfg or StrategyConfig(), costs or Costs()
    d = ind.add_all(df)
    entry_sig = _rule_mask(d, cfg.entry_rules).shift(1, fill_value=False)   # decided at t-1 close
    exit_sig = _rule_mask(d, cfg.exit_rules).shift(1, fill_value=False)
    adv = d["volume"].rolling(20).mean().shift(1)
    dvol = d["ret_1"].rolling(20).std().shift(1).fillna(0.02)
    halted = set(pd.to_datetime(cfg.halted_dates))

    cash, shares, entry_px, entry_dt = initial_capital, 0, 0.0, None
    equity, trades = [], []

    def fill_cost(px, qty, i):
        notional = px * qty
        comm = max(costs.min_commission, costs.commission_per_share * qty) if qty else 0
        part = qty / adv.iloc[i] if adv.iloc[i] and adv.iloc[i] > 0 else 0
        impact = costs.impact_coef * dvol.iloc[i] * np.sqrt(part)
        friction = notional * ((costs.spread_bps / 2 + costs.slippage_bps) / 1e4 + impact)
        return comm + friction

    for i, (ts, bar) in enumerate(d.iterrows()):
        if ts in halted:
            equity.append(cash + shares * bar["close"])
            continue
        if shares:
            exit_px, reason = None, None
            if cfg.stop_loss_pct and bar["low"] <= entry_px * (1 - cfg.stop_loss_pct):
                exit_px, reason = min(bar["open"], entry_px * (1 - cfg.stop_loss_pct)), "stop_loss"
            elif cfg.take_profit_pct and bar["high"] >= entry_px * (1 + cfg.take_profit_pct):
                exit_px, reason = max(bar["open"], entry_px * (1 + cfg.take_profit_pct)), "take_profit"
            elif exit_sig.iloc[i]:
                exit_px, reason = bar["open"], "exit_rule"
            if exit_px is not None:
                c = fill_cost(exit_px, shares, i)
                cash += shares * exit_px - c
                pnl = shares * (exit_px - entry_px) - c - trades[-1]["entry_cost"]
                trades[-1].update(exit_date=str(ts.date()), exit_price=round(exit_px, 4), exit_reason=reason,
                                  pnl=round(pnl, 2), return_pct=round(pnl / (entry_px * shares), 5))
                shares = 0
        elif entry_sig.iloc[i] and i > 0:
            px = bar["open"]
            budget = cash * cfg.position_fraction
            if cfg.max_position_value:
                budget = min(budget, cfg.max_position_value)
            qty = int(budget // (px * (1 + 0.002)))
            if adv.iloc[i] and adv.iloc[i] > 0:
                qty = int(min(qty, costs.max_participation * adv.iloc[i]))
            if qty > 0:
                c = fill_cost(px, qty, i)
                cash -= qty * px + c
                shares, entry_px, entry_dt = qty, px, ts
                trades.append({"entry_date": str(ts.date()), "entry_price": round(px, 4), "shares": qty,
                               "entry_cost": round(c, 2)})
        equity.append(cash + shares * bar["close"])

    eq = pd.Series(equity, index=d.index)
    rets = eq.pct_change().fillna(0)
    bench = d["close"].pct_change().fillna(0)
    closed = [t for t in trades if "pnl" in t]
    wins = [t["pnl"] for t in closed if t["pnl"] > 0]
    losses = [t["pnl"] for t in closed if t["pnl"] <= 0]
    stats = {
        "trades": len(closed), "win_rate": len(wins) / len(closed) if closed else None,
        "avg_win": float(np.mean(wins)) if wins else 0.0, "avg_loss": float(np.mean(losses)) if losses else 0.0,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses and sum(losses) else None,
        "expectancy": float(np.mean([t["pnl"] for t in closed])) if closed else 0.0,
        "final_equity": float(eq.iloc[-1]),
    }
    monthly = (1 + rets).resample("ME").prod() - 1
    annual = (1 + rets).resample("YE").prod() - 1
    return {
        "strategy": asdict(cfg), "costs": asdict(costs), "stats": stats,
        "performance": metrics(rets, bench), "benchmark_buy_hold": metrics(bench),
        "equity_curve": {str(k.date()): round(v, 2) for k, v in eq.items()},
        "monthly_returns": {str(k.date()): round(v, 5) for k, v in monthly.items()},
        "annual_returns": {str(k.year): round(v, 5) for k, v in annual.items()},
        "trade_log": trades,
        "data_source": df.attrs.get("source", "unknown"),
    }


def walk_forward_optimize(df: pd.DataFrame, grid: dict[str, list], base: StrategyConfig | None = None,
                          train_bars: int = 252, test_bars: int = 63, metric: str = "sharpe") -> dict:
    """Pick parameters on each training window, evaluate on the following unseen window."""
    base = base or StrategyConfig()
    keys = list(grid)
    folds, oos = [], []
    start = 0
    while start + train_bars + test_bars <= len(df):
        tr = df.iloc[start:start + train_bars]
        te = df.iloc[start + train_bars - 200 if start + train_bars >= 200 else 0:start + train_bars + test_bars]
        best, best_val = None, -np.inf
        for combo in itertools.product(*grid.values()):
            cfg = StrategyConfig(**{**asdict(base), **dict(zip(keys, combo))})
            v = run_backtest(tr, cfg)["performance"].get(metric) or -np.inf
            if v > best_val:
                best, best_val = cfg, v
        res = run_backtest(te, best)
        test_eq = pd.Series(res["equity_curve"]).iloc[-test_bars:]
        oos.append(test_eq.pct_change().dropna())
        folds.append({"train_end": str(tr.index[-1].date()), "params": dict(zip(keys, [getattr(best, k) for k in keys])),
                      "in_sample": best_val, "out_of_sample_return": float(test_eq.iloc[-1] / test_eq.iloc[0] - 1)})
        start += test_bars
    oos_r = pd.concat(oos) if oos else pd.Series(dtype=float)
    oos_r.index = pd.to_datetime(oos_r.index)
    return {"folds": folds, "out_of_sample": metrics(oos_r) if len(oos_r) > 20 else None}
