"use client";
import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, BarChart } from "recharts";
import { api, pct, usd } from "@/lib/api";

const TABS = ["Executive Overview", "Day Trading", "Stock Research", "Portfolio", "AI Prediction Lab",
  "Strategy Lab", "Risk", "News & Economy", "Trading Journal", "Orders"] as const;
type Tab = (typeof TABS)[number];

function Source({ src, latency, asOf }: { src?: string; latency?: string; asOf?: string }) {
  const color = latency === "real-time" ? "bg-emerald-600" : latency === "simulated" ? "bg-rose-600" : "bg-amber-600";
  return (<div className="text-xs text-slate-400 flex gap-2 items-center">
    <span className={`${color} text-white px-2 py-0.5 rounded uppercase`}>{latency || "unknown"}</span>
    <span>{src}</span>{asOf && <span>· as of {asOf}</span>}</div>);
}

function useLoad<T>(fn: () => Promise<T>, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setErr(null); fn().then(setData).catch((e) => setErr(String(e))); }, deps);
  return { data, err };
}

function Err({ e }: { e: string | null }) { return e ? <div className="card text-rose-300 text-sm">{e}</div> : null; }

function Kpi({ label, value }: { label: string; value: string }) {
  return <div className="card"><div className="text-xs text-slate-400">{label}</div><div className="text-2xl font-semibold mt-1">{value}</div></div>;
}

function Executive() {
  const { data: b, err } = useLoad(() => api("/broker/paper/summary"));
  const { data: h } = useLoad(() => api("/market/SPY/history?bars=250"));
  return (<div className="space-y-4"><Err e={err} />
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Kpi label="Total value (paper)" value={usd(b?.balances?.total_value)} />
      <Kpi label="Cash" value={usd(b?.balances?.cash)} />
      <Kpi label="Buying power" value={usd(b?.balances?.buying_power)} />
      <Kpi label="Realized P/L" value={usd(b?.balances?.realized_pl)} />
    </div>
    <div className="card"><div className="flex justify-between mb-2"><h3 className="font-semibold">Market overview — SPY</h3>
      <Source src={h?.source} latency={h?.latency} asOf={h?.as_of} /></div>
      <ResponsiveContainer width="100%" height={280}><LineChart data={h?.bars || []}>
        <CartesianGrid stroke="#1a3157" /><XAxis dataKey="date" hide /><YAxis domain={["auto", "auto"]} />
        <Tooltip contentStyle={{ background: "#10213b" }} />
        <Line dataKey="close" stroke="#c9a227" dot={false} /><Line dataKey="sma_50" stroke="#60a5fa" dot={false} />
        <Line dataKey="sma_200" stroke="#a78bfa" dot={false} /></LineChart></ResponsiveContainer></div>
    <p className="text-xs text-slate-500">Connect Chase (read-only) and E*TRADE in Settings to see consolidated live accounts.</p></div>);
}

function DayTrading() {
  const { data, err } = useLoad(() => api("/daytrading/top?top=25"));
  return (<div className="space-y-4"><Err e={err} />
    <div className="grid md:grid-cols-3 gap-4">
      {[["Top gainers", data?.gainers], ["Top losers", data?.losers], ["High relative volume", data?.high_rvol]].map(([t, rows]: any) =>
        <div className="card" key={t}><h3 className="font-semibold mb-2">{t}</h3>
          {(rows || []).map((r: any) => <div key={r.symbol} className="flex justify-between text-sm py-0.5">
            <span>{r.symbol}</span><span>{pct(r.change_pct, 2)}</span><span className="text-slate-400">RVOL {r.rvol?.toFixed(2)}</span></div>)}</div>)}
    </div>
    <div className="card overflow-x-auto"><h3 className="font-semibold mb-2">Top 25 intraday opportunities</h3>
      <table className="w-full"><thead><tr>{["Symbol", "Strategy", "Signal", "Price", "Entry zone", "Stop", "Targets", "R:R", "Conf.", "Source / time"].map(h => <th className="th" key={h}>{h}</th>)}</tr></thead>
        <tbody>{(data?.opportunities || []).map((s: any, i: number) => <tr key={i} title={s.supporting_indicators.join("\n")}>
          <td className="td font-semibold">{s.symbol}</td><td className="td">{s.strategy}</td>
          <td className={`td ${s.classification.includes("Buy") ? "text-emerald-400" : s.classification.includes("Sell") || s.classification === "Avoid" ? "text-rose-400" : ""}`}>{s.classification}</td>
          <td className="td">{s.price}</td><td className="td">{s.entry_zone.join(" – ")}</td><td className="td">{s.stop_loss}</td>
          <td className="td">{s.profit_targets.join(" / ")}</td><td className="td">{s.risk_reward.join("/")}</td>
          <td className="td">{pct(s.confidence, 0)}</td><td className="td text-xs text-slate-400">{s.data_latency} · {s.price_timestamp.slice(0, 10)}</td></tr>)}</tbody></table>
      <p className="text-xs text-slate-500 mt-2">Model-generated research signals. Not investment advice; no return is guaranteed.</p></div></div>);
}

function Research() {
  const [sym, setSym] = useState("AAPL");
  const [q, setQ] = useState("AAPL");
  const { data: h, err } = useLoad(() => api(`/market/${q}/history?bars=250`), [q]);
  const { data: sig } = useLoad(() => api(`/signals/${q}?strategy=trend_following`), [q]);
  const { data: scr } = useLoad(() => api("/screener", { method: "POST", body: JSON.stringify({}) }));
  return (<div className="space-y-4"><Err e={err} />
    <div className="flex gap-2"><input className="bg-navy-800 border border-navy-700 rounded px-3 py-2" value={sym} onChange={e => setSym(e.target.value.toUpperCase())} />
      <button className="bg-gold text-navy-900 px-4 rounded font-semibold" onClick={() => setQ(sym)}>Analyze</button></div>
    <div className="card"><div className="flex justify-between"><h3 className="font-semibold">{q}</h3><Source src={h?.source} latency={h?.latency} asOf={h?.as_of} /></div>
      <ResponsiveContainer width="100%" height={260}><LineChart data={h?.bars || []}><XAxis dataKey="date" hide /><YAxis domain={["auto", "auto"]} />
        <Tooltip contentStyle={{ background: "#10213b" }} /><Line dataKey="close" stroke="#c9a227" dot={false} />
        <Line dataKey="bb_upper" stroke="#475569" dot={false} /><Line dataKey="bb_lower" stroke="#475569" dot={false} /></LineChart></ResponsiveContainer>
      {sig && <p className="text-sm mt-2">Trend-following: <b>{sig.classification}</b> · stop {sig.stop_loss} · targets {sig.profit_targets.join(" / ")} · {sig.supporting_indicators.join(", ")}</p>}</div>
    <div className="card overflow-x-auto"><h3 className="font-semibold mb-2">Quantitative ranking (composite factor score)</h3>
      <table className="w-full"><thead><tr>{["Rank", "Symbol", "Composite", "Momentum", "Low vol", "Liquidity", "Beta", "Confidence"].map(h => <th className="th" key={h}>{h}</th>)}</tr></thead>
        <tbody>{(scr?.results || []).map((r: any) => <tr key={r.symbol}><td className="td">{r.rank}</td><td className="td font-semibold">{r.symbol}</td>
          <td className="td">{r.composite?.toFixed(2)}</td><td className="td">{r.momentum?.toFixed(2) ?? "—"}</td><td className="td">{r.low_volatility?.toFixed(2) ?? "—"}</td>
          <td className="td">{r.liquidity?.toFixed(2) ?? "—"}</td><td className="td">{r.market_beta?.toFixed(2) ?? "—"}</td><td className="td">{pct(r.confidence, 0)}</td></tr>)}</tbody></table></div></div>);
}

function Portfolio() {
  const [method, setMethod] = useState("hrp");
  const { data, err } = useLoad(() => api("/portfolio/optimize", { method: "POST",
    body: JSON.stringify({ symbols: ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "JNJ", "V", "PG"], method }) }), [method]);
  return (<div className="space-y-4"><Err e={err} />
    <select className="bg-navy-800 border border-navy-700 rounded px-3 py-2" value={method} onChange={e => setMethod(e.target.value)}>
      {["equal_weight", "min_variance", "max_sharpe", "mean_variance", "risk_parity", "hrp", "max_diversification"].map(m => <option key={m}>{m}</option>)}</select>
    <div className="grid md:grid-cols-4 gap-4">
      <Kpi label="Sharpe" value={data?.metrics?.sharpe?.toFixed(2) ?? "—"} /><Kpi label="Volatility" value={pct(data?.metrics?.volatility)} />
      <Kpi label="Max drawdown" value={pct(data?.metrics?.max_drawdown)} /><Kpi label="95% CVaR (1d)" value={pct(data?.risk?.cvar_hist, 2)} /></div>
    <div className="card"><ResponsiveContainer width="100%" height={260}><BarChart data={Object.entries(data?.weights || {}).map(([k, v]) => ({ k, v }))}>
      <XAxis dataKey="k" /><YAxis tickFormatter={(v) => pct(v, 0)} /><Tooltip formatter={(v: any) => pct(v)} contentStyle={{ background: "#10213b" }} />
      <Bar dataKey="v" fill="#c9a227" /></BarChart></ResponsiveContainer></div></div>);
}

function MLLab() {
  const { data, err } = useLoad(() => api("/ml/AAPL/walkforward"));
  return (<div className="space-y-4"><Err e={err} />{!data && !err && <p>Training walk-forward models…</p>}
    {data && <div className="card overflow-x-auto"><h3 className="font-semibold mb-2">Walk-forward model comparison (out-of-sample, {data.horizon_bars}-bar horizon)</h3>
      <table className="w-full"><thead><tr>{["Model", "Accuracy", "Naive baseline", "Edge", "p-value", "IC", "Latest forecast"].map(h => <th className="th" key={h}>{h}</th>)}</tr></thead>
        <tbody>{Object.entries(data.models).map(([k, m]: any) => <tr key={k}><td className="td">{k}</td><td className="td">{pct(m.directional_accuracy)}</td>
          <td className="td">{pct(m.naive_baseline_accuracy)}</td><td className={`td ${m.edge_vs_baseline > 0 ? "text-emerald-400" : "text-rose-400"}`}>{pct(m.edge_vs_baseline)}</td>
          <td className="td">{m.binomial_p_value_vs_baseline.toFixed(3)}</td><td className="td">{m.information_coefficient.toFixed(3)}</td><td className="td">{pct(m.latest_prediction, 2)}</td></tr>)}</tbody></table>
      <p className="text-xs text-slate-500 mt-2">{data.note}</p></div>}
    {data && <div className="card"><h3 className="font-semibold mb-2">Permutation feature importance</h3>
      <ResponsiveContainer width="100%" height={300}><BarChart layout="vertical" data={Object.entries(data.feature_importance).map(([k, v]) => ({ k, v }))}>
        <XAxis type="number" /><YAxis type="category" dataKey="k" width={100} /><Bar dataKey="v" fill="#60a5fa" /></BarChart></ResponsiveContainer></div>}</div>);
}

function StrategyLab() {
  const [cfg, setCfg] = useState({ symbol: "MSFT", stop: 0.05, tp: 0.15, spread: 5, slip: 2 });
  const [res, setRes] = useState<any>(null);
  const run = () => api("/backtest", { method: "POST", body: JSON.stringify({ symbol: cfg.symbol,
    strategy: { stop_loss_pct: cfg.stop, take_profit_pct: cfg.tp }, costs: { spread_bps: cfg.spread, slippage_bps: cfg.slip } }) }).then(setRes);
  const curve = res ? Object.entries(res.equity_curve).map(([d, v]) => ({ d, v })) : [];
  return (<div className="space-y-4"><div className="card grid grid-cols-2 md:grid-cols-6 gap-2 items-end">
    {(["symbol", "stop", "tp", "spread", "slip"] as const).map(k => <label key={k} className="text-xs text-slate-400">{k}
      <input className="block w-full bg-navy-900 border border-navy-700 rounded px-2 py-1 text-slate-100" value={(cfg as any)[k]}
        onChange={e => setCfg({ ...cfg, [k]: k === "symbol" ? e.target.value.toUpperCase() : Number(e.target.value) })} /></label>)}
    <button className="bg-gold text-navy-900 rounded py-2 font-semibold" onClick={run}>Run backtest</button></div>
    {res && <><div className="grid md:grid-cols-5 gap-4"><Kpi label="Trades" value={String(res.stats.trades)} /><Kpi label="Win rate" value={pct(res.stats.win_rate)} />
      <Kpi label="Profit factor" value={res.stats.profit_factor?.toFixed(2) ?? "—"} /><Kpi label="Sharpe (strategy / buy-hold)" value={`${res.performance.sharpe?.toFixed(2)} / ${res.benchmark_buy_hold.sharpe?.toFixed(2)}`} />
      <Kpi label="Max drawdown" value={pct(res.performance.max_drawdown)} /></div>
      <div className="card"><ResponsiveContainer width="100%" height={260}><LineChart data={curve}><XAxis dataKey="d" hide /><YAxis domain={["auto", "auto"]} />
        <Tooltip contentStyle={{ background: "#10213b" }} /><Line dataKey="v" stroke="#c9a227" dot={false} /></LineChart></ResponsiveContainer>
        <p className="text-xs text-slate-500">Includes commissions, spread, slippage and market impact. Data: {res.data_source}</p></div></>}</div>);
}

function Risk() {
  const [s, setS] = useState({ equity: 100000, entry: 100, stop: 95 });
  const [r, setR] = useState<any>(null);
  return (<div className="card space-y-2 max-w-lg"><h3 className="font-semibold">Position sizing (fixed-fractional, 1% risk)</h3>
    {(["equity", "entry", "stop"] as const).map(k => <label key={k} className="block text-xs text-slate-400">{k}
      <input type="number" className="block w-full bg-navy-900 border border-navy-700 rounded px-2 py-1 text-slate-100" value={s[k]} onChange={e => setS({ ...s, [k]: +e.target.value })} /></label>)}
    <button className="bg-gold text-navy-900 rounded px-4 py-2 font-semibold" onClick={() => api(`/risk/position-size?equity=${s.equity}&entry=${s.entry}&stop=${s.stop}`, { method: "POST" }).then(setR)}>Calculate</button>
    {r && <p className="text-sm">{r.shares} shares · {usd(r.position_value)} · risk {usd(r.dollar_risk)} · limited by {r.binding_constraint}</p>}</div>);
}

function Agents() {
  const { data, err } = useLoad(() => api("/agents/report?symbols=AAPL,MSFT,NVDA,JPM,XOM,V"));
  return (<div className="space-y-3"><Err e={err} />{!data && !err && <p>Agents running…</p>}
    {(data || []).map((a: any) => <div className="card" key={a.agent}><div className="flex justify-between"><h3 className="font-semibold">{a.agent}</h3>
      <span className="text-xs text-slate-400">{a.ts.slice(0, 19)}</span></div>
      <ul className="text-sm list-disc ml-5 mt-1">{a.findings.slice(0, 6).map((f: string, i: number) => <li key={i}>{f}</li>)}</ul>
      {a.evidence?.narrative && <p className="text-sm mt-2 whitespace-pre-wrap">{a.evidence.narrative}</p>}</div>)}</div>);
}

function Orders() {
  const [form, setForm] = useState({ symbol: "AAPL", side: "BUY", quantity: 10, limit_price: 0 });
  const [list, setList] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const refresh = () => api("/orders").then(setList);
  useEffect(() => { refresh(); }, []);
  const act = (p: Promise<any>) => p.then(() => { setMsg(""); refresh(); }).catch(e => setMsg(String(e)));
  return (<div className="space-y-4"><div className="card grid grid-cols-2 md:grid-cols-5 gap-2 items-end">
    {(["symbol", "side", "quantity", "limit_price"] as const).map(k => <label key={k} className="text-xs text-slate-400">{k}
      <input className="block w-full bg-navy-900 border border-navy-700 rounded px-2 py-1 text-slate-100" value={(form as any)[k]}
        onChange={e => setForm({ ...form, [k]: ["quantity", "limit_price"].includes(k) ? +e.target.value : e.target.value.toUpperCase() })} /></label>)}
    <button className="bg-slate-200 text-navy-900 rounded py-2 font-semibold" onClick={() => act(api("/orders/proposals", { method: "POST", body: JSON.stringify({ broker: "paper", ...form }) }))}>Propose (research)</button></div>
    {msg && <div className="card text-rose-300 text-sm">{msg}</div>}
    <div className="card overflow-x-auto"><table className="w-full"><thead><tr>{["ID", "Order", "Status", "Risk checks", "By", "Action"].map(h => <th className="th" key={h}>{h}</th>)}</tr></thead>
      <tbody>{list.map(p => { const o = p.order; const phrase = `APPROVE ${o.side} ${o.quantity} ${o.symbol}`;
        return <tr key={p.id}><td className="td text-xs">{p.id}</td><td className="td">{o.side} {o.quantity} {o.symbol} @ {o.limit_price ?? "MKT"} ({p.broker})</td>
          <td className="td">{p.status}</td><td className="td text-xs">{(p.risk_failures || []).join("; ") || "passed"}</td><td className="td text-xs">{p.proposed_by_role}</td>
          <td className="td">{p.status === "RISK_CHECKED" && <button className="text-gold underline" onClick={() => {
            const t = prompt(`Live-order confirmation. Type exactly:\n${phrase}`); if (t) act(api(`/orders/${p.id}/approve`, { method: "POST", body: JSON.stringify({ confirm_text: t }) })); }}>Approve…</button>}
            {p.status === "APPROVED" && <button className="text-emerald-400 underline" onClick={() => act(api(`/orders/${p.id}/submit`, { method: "POST" }))}>Submit to broker</button>}</td></tr>; })}</tbody></table>
      <p className="text-xs text-slate-500 mt-2">Proposals are research recommendations, not orders. Only a human trader can approve and submit. AI agents cannot.</p></div></div>);
}

function Journal() {
  const { data } = useLoad(() => api("/broker/paper/summary"));
  const { data: audit } = useLoad(() => api("/audit?n=50"));
  return (<div className="space-y-4"><div className="card"><h3 className="font-semibold mb-2">Positions (paper)</h3>
    {(data?.positions || []).map((p: any) => <div key={p.symbol} className="text-sm">{p.symbol} {p.quantity} @ {p.avg_cost} · unrealized {usd(p.unrealized_pl)}</div>)}</div>
    <div className="card"><h3 className="font-semibold mb-2">Audit log {audit && (audit.chain_valid ? "✓ chain intact" : "⚠ chain broken")}</h3>
      {(audit?.entries || []).slice().reverse().map((e: any) => <div key={e.hash} className="text-xs font-mono text-slate-300">{e.ts.slice(0, 19)} {e.actor} {e.action} {JSON.stringify(e.detail).slice(0, 120)}</div>)}</div></div>);
}

export default function Home() {
  const [tab, setTab] = useState<Tab>("Executive Overview");
  const view: Record<Tab, JSX.Element> = { "Executive Overview": <Executive />, "Day Trading": <DayTrading />, "Stock Research": <Research />,
    Portfolio: <Portfolio />, "AI Prediction Lab": <MLLab />, "Strategy Lab": <StrategyLab />, Risk: <Risk />, "News & Economy": <Agents />,
    "Trading Journal": <Journal />, Orders: <Orders /> };
  return (<div className="flex min-h-screen flex-col md:flex-row">
    <nav className="md:w-56 bg-navy-800 border-r border-navy-700 p-3 flex md:flex-col gap-1 overflow-x-auto">
      <div className="text-gold font-bold text-lg mb-3 hidden md:block">GlobalBLOCS<div className="text-xs text-slate-400 font-normal">Quant Intelligence</div></div>
      {TABS.map(t => <button key={t} onClick={() => setTab(t)} className={`text-left px-3 py-2 rounded text-sm whitespace-nowrap ${t === tab ? "bg-navy-700 text-gold" : "hover:bg-navy-700"}`}>{t}</button>)}</nav>
    <main className="flex-1 p-4 md:p-6"><h1 className="text-xl font-semibold mb-4">{tab}</h1>{view[tab]}</main></div>);
}
