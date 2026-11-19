"use client";
import { useEffect, useState } from "react";
import { api, apiBase, isDesktopApp, isPhoneApp, pairWithDesktop, signIn } from "@/lib/api";

const input = "block w-full bg-navy-900 border border-navy-700 rounded px-3 py-2 text-slate-100 mt-1";
const btn = "bg-gold text-navy-900 rounded px-4 py-2 font-semibold disabled:opacity-40";

/** Shown when no server is configured (phone) or the server asks for sign-in (passcode mode). */
export function ConnectScreen({ onDone }: { onDone: () => void }) {
  const phone = isPhoneApp();
  const desktop = isDesktopApp();
  const [mode, setMode] = useState<"pair" | "signin">(phone ? "pair" : "signin");
  const [server, setServer] = useState(desktop ? apiBase() : (typeof localStorage !== "undefined" && localStorage.getItem("gb_server")) || "http://");
  const [code, setCode] = useState("");
  const [user, setUser] = useState("admin");
  const [pass, setPass] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const go = async () => {
    setBusy(true); setErr("");
    try {
      const s = server.trim().replace(/\/+$/, "");
      if (mode === "pair") await pairWithDesktop(s, code.trim(), phone ? "GlobalBLOCS phone" : "Browser");
      else await signIn(s, user.trim(), pass);
      onDone();
    } catch (e: any) { setErr(e.message || String(e)); } finally { setBusy(false); }
  };

  return (<div className="min-h-screen flex items-center justify-center p-4" style={{ paddingTop: "env(safe-area-inset-top)" }}>
    <div className="card w-full max-w-md space-y-4">
      <div><div className="text-gold font-bold text-xl">GlobalBLOCS Quant</div>
        <div className="text-sm text-slate-400">{desktop ? "Sign in to continue" : "Connect to your GlobalBLOCS engine"}</div></div>
      {!desktop && <div className="flex gap-2 text-sm">
        {(["pair", "signin"] as const).map(m => <button key={m} onClick={() => setMode(m)}
          className={`flex-1 rounded py-2 ${mode === m ? "bg-navy-700 text-gold" : "border border-navy-700"}`}>
          {m === "pair" ? "Pair with my desktop" : "Sign in to a server"}</button>)}</div>}
      {!desktop && <label className="block text-xs text-slate-400">Server address
        <input className={input} value={server} onChange={e => setServer(e.target.value)} autoCapitalize="none" autoCorrect="off" inputMode="url"
          placeholder={mode === "pair" ? "http://192.168.1.20:8765" : "https://api.yourdomain.com"} />
        <span className="block mt-1">{mode === "pair" ? "Shown on the desktop under Pair Phone. Both devices must be on the same Wi-Fi."
          : "Your cloud (AWS) server address."}</span></label>}
      {mode === "pair" && !desktop ? <label className="block text-xs text-slate-400">6-digit pairing code
        <input className={`${input} tracking-[0.5em] text-center text-xl`} value={code} maxLength={6} inputMode="numeric"
          onChange={e => setCode(e.target.value.replace(/\D/g, ""))} /></label>
        : <><label className="block text-xs text-slate-400">Username<input className={input} value={user} onChange={e => setUser(e.target.value)} autoCapitalize="none" /></label>
          <label className="block text-xs text-slate-400">Passcode<input type="password" className={input} value={pass} onChange={e => setPass(e.target.value)}
            onKeyDown={e => e.key === "Enter" && go()} /></label></>}
      {err && <p className="text-sm text-rose-300">{err}</p>}
      <button className={`${btn} w-full`} disabled={busy || (mode === "pair" && !desktop ? code.length !== 6 : !pass)} onClick={go}>
        {busy ? "Connecting…" : mode === "pair" && !desktop ? "Pair" : "Sign in"}</button>
      <p className="text-xs text-slate-500">Research signals are not investment advice and never guarantee returns.</p>
    </div></div>);
}

/** Desktop-only tab: generate a pairing code and manage paired phones. */
export function PairPhone() {
  const [code, setCode] = useState<any>(null);
  const [devices, setDevices] = useState<Record<string, any>>({});
  const [err, setErr] = useState("");
  const [left, setLeft] = useState(0);
  const load = () => api("/pairing/devices").then(setDevices).catch(e => setErr(String(e)));
  useEffect(() => { load(); }, []);
  useEffect(() => { if (left <= 0) return; const t = setTimeout(() => setLeft(left - 1), 1000); return () => clearTimeout(t); }, [left]);
  const start = () => { setErr(""); api("/pairing/start", { method: "POST" }).then(c => { setCode(c); setLeft(c.expires_in_seconds); })
    .catch(e => setErr(String(e).replace(/^Error: \d+: /, ""))); };
  return (<div className="space-y-4 max-w-2xl">
    <div className="card space-y-3"><h3 className="font-semibold">Pair your phone</h3>
      <ol className="text-sm list-decimal ml-5 text-slate-300 space-y-1">
        <li>Install the GlobalBLOCS Quant app on your phone (Android APK or iPhone build from the release page).</li>
        <li>Connect the phone to the same Wi-Fi as this computer.</li>
        <li>In the app, choose <b>Pair with my desktop</b>, then enter the address and code shown here.</li></ol>
      <button className="bg-gold text-navy-900 rounded px-4 py-2 font-semibold" onClick={start}>Generate pairing code</button>
      {err && <p className="text-sm text-rose-300">{err}</p>}
      {code && left > 0 && <div className="bg-navy-900 rounded-lg p-4 text-center">
        <div className="text-4xl font-mono tracking-[0.4em] text-gold">{code.code}</div>
        <div className="text-sm mt-2">Address: {code.server_urls.length ? code.server_urls.map((u: string) => <b key={u} className="mx-1">{u}</b>)
          : <span className="text-rose-300">no Wi-Fi address found — is this computer on a network?</span>}</div>
        <div className="text-xs text-slate-400 mt-1">Expires in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")} · single use</div></div>}
      {code && left <= 0 && <p className="text-sm text-slate-400">Code expired. Generate a new one.</p>}
      <p className="text-xs text-slate-500">If Windows asks whether to allow GlobalBLOCS on private networks, choose Allow. Wi-Fi traffic between
        phone and desktop is not encrypted, so pair only on a network you trust (home, not public Wi-Fi). For use away from home, deploy the cloud server.</p></div>
    <div className="card"><h3 className="font-semibold mb-2">Paired devices</h3>
      {Object.keys(devices).length === 0 && <p className="text-sm text-slate-400">None yet.</p>}
      {Object.entries(devices).map(([id, d]) => <div key={id} className="flex justify-between items-center text-sm py-1 border-t border-navy-700">
        <span>{d.name} · {d.role} · paired {d.paired_at}</span>
        <button className="text-rose-300 underline" onClick={() => api(`/pairing/devices/${id}`, { method: "DELETE" }).then(load)}>Unpair</button></div>)}</div>
  </div>);
}
