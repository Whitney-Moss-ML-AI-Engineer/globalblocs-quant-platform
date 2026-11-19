"""Coordinated research agents.

Each agent produces a traceable AgentReport (findings + evidence + sources + timestamp). Agents run
deterministic quantitative code; an LLM (if configured) is used only to write the executive narrative
from those reports, grounded by retrieved documents (RAG). Agents can create order *proposals* via
the OrderManager but have no permission to approve or submit them."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import pandas as pd

from agents.rag import Retriever
from backtesting.engine import run_backtest
from ml.nlp import sentiment
from ml.pipeline import walk_forward
from quant import factors, portfolio, risk, signals


@dataclass
class AgentReport:
    agent: str
    findings: list
    evidence: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Ctx(dict):
    """Shared blackboard passed between agents."""


def _src(prices):
    return sorted({df.attrs.get("source", "unknown") + " | " + df.attrs.get("latency", "?") for df in prices.values()})


def market_intelligence(c: Ctx):
    b = c["benchmark"]
    r = b["close"].pct_change()
    trend = "uptrend" if b["close"].iloc[-1] > b["close"].rolling(200).mean().iloc[-1] else "downtrend"
    vol = float(r.tail(20).std() * 252 ** 0.5)
    return AgentReport("Market Intelligence", [f"Benchmark in {trend}", f"20-day realized vol {vol:.1%}"],
                       {"trend": trend, "vol_20": vol}, [b.attrs.get("source", "?")])


def stock_screening(c: Ctx):
    sc = factors.composite(c["prices"], c.get("fundamentals"), c["benchmark"]["close"])
    c["scores"] = sc
    top = sc.head(10)
    return AgentReport("Stock Screening", [f"#{int(r['rank'])} {s} composite {r['composite']:.2f} (conf {r['confidence']:.2f})"
                                          for s, r in top.iterrows()], {"ranking": sc.round(3).reset_index().to_dict("records")},
                       _src(c["prices"]))


def technical_analysis(c: Ctx):
    sigs = signals.best_signals(c["prices"], top=25)
    c["signals"] = sigs
    return AgentReport("Technical Analysis", [f"{s['symbol']} {s['strategy']}: {s['classification']} (score {s['score']})" for s in sigs[:10]],
                       {"signals": sigs}, _src(c["prices"]))


def fundamental_research(c: Ctx):
    f = c.get("fundamentals")
    if f is None or f.empty:
        return AgentReport("Fundamental Research", ["No fundamentals loaded; connect SEC EDGAR/financial data provider"])
    cheap = f.sort_values("pe").head(5).index.tolist() if "pe" in f else []
    return AgentReport("Fundamental Research", [f"Lowest P/E: {', '.join(cheap)}"], {"fundamentals": f.round(3).to_dict()},
                       ["SEC EDGAR XBRL / provider"])


def news_sentiment(c: Ctx):
    news = c.get("news", {})
    out = {s: sentiment(" ".join(t)) for s, t in news.items()}
    risks = [f"{s}: {', '.join(v['emerging_risks'])}" for s, v in out.items() if v.get("emerging_risks")]
    return AgentReport("News & Sentiment", [f"{s}: {v['label']} ({v['score']})" for s, v in out.items()] + risks, out,
                       c.get("news_sources", []))


def quantitative_research(c: Ctx):
    sc = c["scores"]
    corr = sc.drop(columns=["composite", "percentile", "rank", "confidence"]).corr().round(2)
    return AgentReport("Quantitative Research", ["Factor correlation matrix computed; watch for redundant factors (|rho|>0.7)"],
                       {"factor_correlation": corr.to_dict()})


def machine_learning(c: Ctx):
    sym = c["scores"].index[0]
    res = walk_forward(c["prices"][sym], models=["ridge", "random_forest"], splits=4, n_boot=200)
    best = res["models"][res["best_model_by_ic"]]
    return AgentReport("Machine Learning", [f"{sym}: best model {res['best_model_by_ic']} OOS accuracy {best['directional_accuracy']:.1%} vs naive {best['naive_baseline_accuracy']:.1%} "
                                            f"(p={best['binomial_p_value_vs_baseline']:.3f})"], res)


def risk_management(c: Ctx):
    rets = pd.DataFrame({s: d["close"].pct_change() for s, d in c["prices"].items()}).dropna().tail(504)
    c["returns"] = rets
    w = portfolio.equal_weight(rets.columns)
    pr = risk.portfolio_risk(w, rets)
    return AgentReport("Risk Management", [f"Equal-weight vol {pr['portfolio_volatility']:.1%}, 1-day 95% VaR {pr['var_hist']:.2%}"],
                       {k: v for k, v in pr.items() if k != "correlation"})


def portfolio_optimization(c: Ctx):
    top = c["scores"].head(min(10, len(c["scores"]))).index
    w = portfolio.optimize(c["returns"][top], "hrp")
    c["weights"] = w
    return AgentReport("Portfolio Optimization", [f"HRP weights: " + ", ".join(f"{k} {v:.1%}" for k, v in w.items())], {"weights": w.round(4).to_dict()})


def trading_strategy(c: Ctx):
    sym = c["scores"].index[0]
    bt = run_backtest(c["prices"][sym])
    return AgentReport("Trading Strategy", [f"{sym} trend strategy backtest Sharpe {bt['performance']['sharpe']}, "
                                            f"max DD {bt['performance']['max_drawdown']:.1%}, {bt['stats']['trades']} trades (after costs)"],
                       {"stats": bt["stats"], "performance": bt["performance"]})


def brokerage_monitoring(c: Ctx):
    bro = c.get("brokers", {})
    rows = {}
    for n, b in bro.items():
        try:
            rows[n] = b.balances(b.accounts()[0].get("accountId", ""))
        except Exception as e:  # noqa: BLE001 - report, never crash the research run
            rows[n] = {"error": str(e)}
    return AgentReport("Brokerage Monitoring", [f"{n}: {r}" for n, r in rows.items()] or ["No brokerage connected"], rows)


AGENTS = [market_intelligence, stock_screening, technical_analysis, fundamental_research, news_sentiment,
          quantitative_research, machine_learning, risk_management, portfolio_optimization, trading_strategy,
          brokerage_monitoring]


def executive_analyst(reports: list[AgentReport], retriever: Retriever | None = None) -> AgentReport:
    lines = [f"[{r.agent}] " + "; ".join(map(str, r.findings[:3])) for r in reports]
    context = retriever.search("investment methodology risk policy", k=3) if retriever else []
    narrative = None
    if os.getenv("ANTHROPIC_API_KEY"):
        import httpx
        prompt = ("Write a concise investment research brief from these agent findings. Do not promise returns; "
                  "state uncertainty and risks.\n\n" + "\n".join(lines) + "\n\nPolicy context:\n" +
                  "\n".join(d["text"][:800] for d in context))
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=60,
                       headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                       json={"model": os.getenv("LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": 1200,
                             "messages": [{"role": "user", "content": prompt}]})
        if r.status_code == 200:
            narrative = r.json()["content"][0]["text"]
    return AgentReport("Executive Investment Analyst", lines, {"narrative": narrative, "retrieved": context},
                       [s for r in reports for s in r.sources])


def run_all(ctx: Ctx, retriever: Retriever | None = None) -> list[dict]:
    reports = []
    for agent in AGENTS:
        try:
            reports.append(agent(ctx))
        except Exception as e:  # noqa: BLE001
            reports.append(AgentReport(agent.__name__, [f"agent error: {e}"]))
    reports.append(executive_analyst(reports, retriever))
    return [asdict(r) for r in reports]
