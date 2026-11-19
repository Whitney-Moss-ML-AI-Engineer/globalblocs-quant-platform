import os

os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("AUDIT_LOG", "/tmp/gb_test_audit.jsonl")

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backtesting.engine import Costs, StrategyConfig, run_backtest
from brokerage.base import OrderRequest
from brokerage.execution import AuditLog, OrderManager, RiskLimits
from brokerage.paper import PaperBroker
from data_pipelines.market_data import SyntheticProvider
from ml.pipeline import build_dataset, walk_forward
from quant import factors, indicators as ind, portfolio, risk, signals

P = SyntheticProvider()


@pytest.fixture(scope="module")
def df():
    return P.history("TEST", 600)


def test_rsi_bounds_and_sma(df):
    r = ind.rsi(df["close"]).dropna()
    assert r.between(0, 100).all()
    assert np.isclose(ind.sma(df["close"], 5).iloc[-1], df["close"].tail(5).mean())


def test_indicators_are_causal(df):
    full = ind.add_all(df)
    cut = ind.add_all(df.iloc[:400])
    cols = ["sma_50", "rsi_14", "macd", "atr_14", "adx", "bb_upper"]
    pd.testing.assert_frame_equal(full[cols].iloc[:400], cut[cols], check_exact=False, rtol=1e-9)


def test_signal_fields(df):
    s = signals.generate_signal("TEST", df, "breakout")
    for k in ["entry_zone", "stop_loss", "profit_targets", "risk_reward", "confidence", "invalidation",
              "price_timestamp", "data_source", "disclaimer"]:
        assert k in s
    assert s["stop_loss"] < s["price"] < s["profit_targets"][0]
    assert s["data_latency"] == "simulated"


def test_composite_scores():
    prices = {s: P.history(s, 400) for s in "ABCDEFGH"}
    out = factors.composite(prices, bench=P.history("SPY", 400)["close"])
    assert out["rank"].min() == 1 and out["confidence"].between(0, 1).all()


@pytest.mark.parametrize("m", ["equal_weight", "min_variance", "max_sharpe", "risk_parity", "hrp", "max_diversification"])
def test_optimizers_sum_to_one(m):
    rets = pd.DataFrame({s: P.history(s, 400)["close"].pct_change() for s in "ABCDE"}).dropna()
    w = portfolio.optimize(rets, m, max_weight=0.5)
    assert np.isclose(w.sum(), 1) and (w >= -1e-9).all()
    if m != "hrp":
        assert w.max() <= 0.5 + 1e-6


def test_risk_metrics(df):
    m = risk.metrics(df["close"].pct_change(), df["close"].pct_change())
    assert np.isclose(m["beta"], 1, atol=1e-6) and m["max_drawdown"] <= 0 and m["cvar_hist"] >= m["var_hist"]


def test_backtest_costs_reduce_returns(df):
    free = run_backtest(df, StrategyConfig(), Costs(spread_bps=0, slippage_bps=0, impact_coef=0))
    costly = run_backtest(df, StrategyConfig(), Costs(spread_bps=50, slippage_bps=20, commission_per_share=0.01))
    if free["stats"]["trades"]:
        assert costly["stats"]["final_equity"] < free["stats"]["final_equity"]


def test_ml_no_leakage(df):
    X, y = build_dataset(df, horizon=5)
    assert X.index.max() < df.index[-5]
    res = walk_forward(df, models=["ridge"], splits=3, n_boot=50)
    assert 0 <= res["models"]["ridge"]["directional_accuracy"] <= 1


def _oms(tmp_path):
    b = PaperBroker(cash=100_000, price_fn=lambda s: 50.0)
    return OrderManager({"paper": b}, RiskLimits(), AuditLog(str(tmp_path / "a.jsonl")))


def test_agent_cannot_approve(tmp_path):
    oms = _oms(tmp_path)
    p = oms.propose("paper", OrderRequest("ABC", "BUY", 10, "LIMIT", 51.0), "agent-7", "agent")
    with pytest.raises(PermissionError):
        oms.approve(p["id"], "agent-7", "agent", "APPROVE BUY 10 ABC")


def test_full_human_flow_and_audit_chain(tmp_path):
    oms = _oms(tmp_path)
    p = oms.propose("paper", OrderRequest("ABC", "BUY", 10, "LIMIT", 51.0), "whitney", "trader")
    assert p["status"] == "RISK_CHECKED"
    with pytest.raises(ValueError):
        oms.approve(p["id"], "whitney", "trader", "yes")
    oms.approve(p["id"], "whitney", "trader", "APPROVE BUY 10 ABC")
    r = oms.submit(p["id"], "whitney", "trader")
    assert r["broker_response"]["status"] == "FILLED"
    assert oms.audit.verify()


def test_risk_limit_rejects_oversized(tmp_path):
    oms = _oms(tmp_path)
    p = oms.propose("paper", OrderRequest("ABC", "BUY", 1000, "LIMIT", 50.0), "whitney", "trader")
    assert p["status"] == "REJECTED"


def test_api_endpoints():
    from backend.app.main import app
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    assert len(c.post("/screener", json={"symbols": ["AAPL", "MSFT", "NVDA", "JPM"]}).json()["results"]) == 4
    assert c.get("/signals/AAPL?strategy=momentum").json()["symbol"] == "AAPL"
    assert "weights" in c.post("/portfolio/optimize", json={"symbols": ["AAPL", "MSFT", "JPM"], "method": "hrp"}).json()
    assert "stats" in c.post("/backtest", json={"symbol": "AAPL"}).json()
    assert len(c.get("/daytrading/top?top=5").json()["opportunities"]) == 5


def test_phone_pairing_and_remote_auth(tmp_path, monkeypatch):
    from backend.app import security
    from backend.app.main import app
    monkeypatch.setenv("MOBILE_ACCESS", "true")
    security.devices.path = tmp_path / "devices.json"
    local = TestClient(app)                                   # desktop (local client)
    phone = TestClient(app, client=("192.168.1.50", 50000))  # phone on Wi-Fi
    assert phone.get("/health").status_code == 200
    assert phone.get("/signals/AAPL").status_code == 401        # local bypass never applies to the phone
    assert phone.post("/pairing/start").status_code in (401, 403)
    code = local.post("/pairing/start").json()["code"]
    assert phone.post("/pairing/claim", json={"code": "000000" if code != "000000" else "111111"}).status_code == 403
    tok = phone.post("/pairing/claim", json={"code": code, "device_name": "Pixel"}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    assert phone.get("/signals/AAPL", headers=h).status_code == 200
    assert phone.post("/pairing/claim", json={"code": code}).status_code == 403   # single use
    local.delete(f"/pairing/devices/{tok['device_id']}")
    assert phone.get("/signals/AAPL", headers=h).status_code == 401              # revoked
