"""GlobalBLOCS Quant API (FastAPI). Run: uvicorn backend.app.main:app --port 8000
Interactive API docs at /docs (OpenAPI)."""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from agents.orchestrator import Ctx, run_all
from agents.rag import Retriever
from backend.app.security import issue_token, require, verify_password
from backtesting.engine import Costs, StrategyConfig, run_backtest, walk_forward_optimize
from brokerage.base import NotSupported, OrderRequest
from brokerage.execution import AuditLog, OrderManager, RiskLimits
from brokerage.paper import PaperBroker
from data_pipelines.market_data import get_provider
from ml.pipeline import walk_forward
from quant import factors, indicators as ind, portfolio, risk, signals

app = FastAPI(title="GlobalBLOCS Quant Platform API", version="1.0.0",
              description="Research outputs are not investment advice and do not guarantee returns.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,app://.").split(","),
                   allow_methods=["*"], allow_headers=["*"])

DEFAULT_UNIVERSE = os.getenv("DEFAULT_UNIVERSE", "AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,XOM,JNJ,V,PG,HD,COST,AVGO,LLY").split(",")
provider = get_provider()
audit = AuditLog(os.getenv("AUDIT_LOG", "data/audit.jsonl"))


@lru_cache(maxsize=512)
def history(symbol: str) -> pd.DataFrame:
    return provider.history(symbol.upper(), days=int(os.getenv("HISTORY_DAYS", "600")))


def last_price(sym: str) -> float:
    return float(history(sym)["close"].iloc[-1])


brokers = {"paper": PaperBroker(cash=float(os.getenv("PAPER_CASH", "100000")), price_fn=last_price)}
limits = RiskLimits(
    max_position_value=float(os.getenv("MAX_POSITION_VALUE", "10000")),
    max_position_pct=float(os.getenv("MAX_POSITION_PCT", "0.10")),
    max_portfolio_exposure_pct=float(os.getenv("MAX_EXPOSURE_PCT", "0.95")),
    daily_loss_limit=float(os.getenv("DAILY_LOSS_LIMIT", "1000")),
    max_orders_per_day=int(os.getenv("MAX_ORDERS_PER_DAY", "25")),
    live_trading_enabled=os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true")
oms = OrderManager(brokers, limits, audit)


def _js(x):
    """JSON-safe conversion (NaN -> null)."""
    if isinstance(x, pd.DataFrame):
        return x.replace([np.inf, -np.inf], np.nan).astype(object).where(x.notna(), None).to_dict("records")
    return x


# ---------------- auth ----------------
@app.post("/auth/token", tags=["auth"])
def login(form: OAuth2PasswordRequestForm = Depends()):
    stored = os.getenv("ADMIN_PASSWORD_HASH")
    if not stored or form.username != os.getenv("ADMIN_USER", "admin") or not verify_password(form.password, stored):
        raise HTTPException(401, "bad credentials")
    return {"access_token": issue_token(form.username, "admin"), "token_type": "bearer"}


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "data_provider": provider.name, "live_trading_enabled": limits.live_trading_enabled,
            "audit_chain_valid": audit.verify()}


# ---------------- market data & research ----------------
@app.get("/market/{symbol}/history", tags=["market"])
def market_history(symbol: str, bars: int = 250, u=Depends(require("read"))):
    df = history(symbol)
    d = ind.add_all(df).tail(bars).reset_index(names="date")
    d["date"] = d["date"].astype(str)
    return {"symbol": symbol.upper(), "source": df.attrs["source"], "latency": df.attrs["latency"],
            "as_of": str(df.index[-1]), "bars": _js(d)}


class ScreenReq(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: DEFAULT_UNIVERSE)
    benchmark: str = "SPY"
    weights: dict[str, float] | None = None


@app.post("/screener", tags=["research"])
def screener(req: ScreenReq, u=Depends(require("research"))):
    prices = {s.upper(): history(s) for s in req.symbols}
    out = factors.composite(prices, bench=history(req.benchmark)["close"], weights=req.weights)
    return {"as_of": str(history(req.benchmark).index[-1]), "source": provider.name,
            "results": _js(out.reset_index(names="symbol"))}


@app.get("/signals/{symbol}", tags=["research"])
def signal(symbol: str, strategy: str = "momentum", u=Depends(require("research"))):
    try:
        return signals.generate_signal(symbol.upper(), history(symbol), strategy)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/daytrading/top", tags=["research"])
def day_trading(symbols: str | None = None, top: int = 25, u=Depends(require("research"))):
    syms = symbols.split(",") if symbols else DEFAULT_UNIVERSE
    prices = {s.upper(): history(s) for s in syms}
    movers = sorted(({"symbol": s, "change_pct": float(d["close"].pct_change().iloc[-1]),
                      "gap_pct": float(d["open"].iloc[-1] / d["close"].iloc[-2] - 1),
                      "rvol": float(ind.relative_volume(d).iloc[-1])} for s, d in prices.items()),
                    key=lambda r: r["change_pct"], reverse=True)
    return {"opportunities": signals.best_signals(prices, top=top), "gainers": movers[:5], "losers": movers[-5:][::-1],
            "high_rvol": sorted(movers, key=lambda r: -r["rvol"])[:10]}


class OptReq(BaseModel):
    symbols: list[str]
    method: str = "max_sharpe"
    max_weight: float = 0.35
    capital: float = 100_000
    lookback: int = 504


@app.post("/portfolio/optimize", tags=["portfolio"])
def optimize(req: OptReq, u=Depends(require("research"))):
    rets = pd.DataFrame({s.upper(): history(s)["close"].pct_change() for s in req.symbols}).dropna().tail(req.lookback)
    w = portfolio.optimize(rets, req.method, req.max_weight)
    px = pd.Series({s: last_price(s) for s in w.index})
    pr = rets @ w
    return {"method": req.method, "weights": w.round(4).to_dict(),
            "allocation": _js(portfolio.allocate_capital(w, px, req.capital).reset_index(names="symbol")),
            "metrics": risk.metrics(pr, history("SPY")["close"].pct_change()),
            "risk": {k: v for k, v in risk.portfolio_risk(w, rets).items() if k != "correlation"}}


class BTReq(BaseModel):
    symbol: str
    strategy: dict = Field(default_factory=dict)
    costs: dict = Field(default_factory=dict)
    initial_capital: float = 100_000
    optimize_grid: dict[str, list] | None = None


@app.post("/backtest", tags=["strategy-lab"])
def backtest(req: BTReq, u=Depends(require("research"))):
    df = history(req.symbol)
    cfg = StrategyConfig(**req.strategy)
    if req.optimize_grid:
        return walk_forward_optimize(df, req.optimize_grid, cfg)
    return run_backtest(df, cfg, Costs(**req.costs), req.initial_capital)


@app.get("/ml/{symbol}/walkforward", tags=["ml"])
def ml_walkforward(symbol: str, horizon: int = 5, u=Depends(require("research"))):
    return walk_forward(history(symbol), horizon=horizon)


@app.get("/agents/report", tags=["agents"])
def agents_report(symbols: str | None = None, u=Depends(require("research"))):
    syms = symbols.split(",") if symbols else DEFAULT_UNIVERSE
    ctx = Ctx(prices={s.upper(): history(s) for s in syms}, benchmark=history("SPY"), brokers=brokers)
    return run_all(ctx, Retriever())


@app.post("/risk/position-size", tags=["risk"])
def position_size(equity: float, entry: float, stop: float, risk_per_trade: float = 0.01, u=Depends(require("read"))):
    return risk.position_size(equity, entry, stop, risk_per_trade, limits.max_position_pct)


# ---------------- brokerage ----------------
@app.get("/broker/{name}/summary", tags=["brokerage"])
def broker_summary(name: str, u=Depends(require("read"))):
    b = brokers.get(name)
    if not b:
        raise HTTPException(404, f"{name} not connected. Connect it from Settings (OAuth).")
    acct = b.accounts()[0].get("accountId", "")
    try:
        orders = b.orders(acct)
    except NotSupported:
        orders = []
    return {"broker": name, "read_only": not b.can_trade, "accounts": b.accounts(), "balances": b.balances(acct),
            "positions": b.positions(acct), "open_orders": [o for o in orders if o.get("status") == "OPEN"]}


# ---------------- orders (research vs execution separated) ----------------
class ProposalReq(BaseModel):
    broker: str = "paper"
    symbol: str
    side: str
    quantity: int
    order_type: str = "LIMIT"
    limit_price: float | None = None
    stop_price: float | None = None
    rationale: str = ""


@app.post("/orders/proposals", tags=["orders"])
def propose(req: ProposalReq, u=Depends(require("propose"))):
    o = OrderRequest(symbol=req.symbol.upper(), side=req.side.upper(), quantity=req.quantity, order_type=req.order_type,
                     limit_price=req.limit_price, stop_price=req.stop_price)
    try:
        return oms.propose(req.broker, o, u["user"], u["role"], req.rationale)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class ApproveReq(BaseModel):
    confirm_text: str


@app.post("/orders/{pid}/approve", tags=["orders"])
def approve(pid: str, req: ApproveReq, u=Depends(require("approve"))):
    try:
        return oms.approve(pid, u["user"], u["role"], req.confirm_text)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, str(e)) from e


@app.post("/orders/{pid}/submit", tags=["orders"])
def submit(pid: str, u=Depends(require("submit"))):
    try:
        return oms.submit(pid, u["user"], u["role"])
    except (ValueError, PermissionError, NotSupported) as e:
        raise HTTPException(400, str(e)) from e


@app.get("/orders", tags=["orders"])
def list_orders(u=Depends(require("read"))):
    return list(oms.proposals.values())


@app.get("/audit", tags=["system"])
def audit_tail(n: int = 100, u=Depends(require("read"))):
    return {"chain_valid": audit.verify(), "entries": audit.tail(n)}


@app.websocket("/ws/signals")
async def ws_signals(ws: WebSocket):
    await ws.accept()
    while True:
        prices = {s: history(s) for s in DEFAULT_UNIVERSE[:8]}
        await ws.send_json({"signals": signals.best_signals(prices, ["momentum", "breakout", "vwap"], top=10)})
        await asyncio.sleep(int(os.getenv("SIGNAL_REFRESH_SECONDS", "30")))
