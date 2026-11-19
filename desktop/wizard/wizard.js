const sections = [...document.querySelectorAll("section[data-step]")];
const $ = (id) => document.getElementById(id);
let i = 0, sys = null, installed = false;

$("steps").innerHTML = sections.map((s, n) => `<div class="step" data-n="${n}">${n + 1}. ${s.dataset.step}</div>`).join("");

const gates = {
  "Disclosures": () => $("acceptLicense").checked && $("acceptRisk").checked,
  "System check": () => !!(sys && sys.python && sys.keychain),
  "Install engine": () => installed,
  "Security": () => {
    const p = $("pass1").value, ok = p.length >= 12 && p === $("pass2").value;
    $("passMsg").textContent = ok ? "" : "Passcode must be at least 12 characters and both entries must match.";
    return ok;
  },
};

function render() {
  sections.forEach((s, n) => s.classList.toggle("hidden", n !== i));
  document.querySelectorAll(".step").forEach((el, n) => { el.classList.toggle("active", n === i); el.classList.toggle("done", n < i); });
  $("back").disabled = i === 0;
  $("next").textContent = i === sections.length - 1 ? "Finish" : "Next";
  const step = sections[i].dataset.step;
  if (step === "System check" && !sys) check();
  if (step === "Finish") summarize();
}

async function check() {
  $("sysTable").innerHTML = "<tr><td>Checking…</td></tr>";
  sys = await window.wizard.systemCheck();
  const row = (k, v, ok) => `<tr><td>${k}</td><td class="${ok ? "ok" : "bad"}">${ok ? "✔" : "✖"} ${v}</td></tr>`;
  $("sysTable").innerHTML = row("Python 3.10+", sys.python ? `${sys.python.version} (${sys.python.exe})` : "not found", !!sys.python)
    + row("OS keychain encryption", sys.keychain ? "available" : "unavailable", sys.keychain)
    + row("Free disk space", sys.freeDiskGB != null ? `${sys.freeDiskGB} GB` : "unknown", sys.freeDiskGB == null || sys.freeDiskGB >= 3)
    + row("Platform", sys.platform, true) + row("Data folder", sys.dataDir, true);
  $("pyHelp").classList.toggle("hidden", !!sys.python);
}

$("recheck").onclick = () => { sys = null; check(); };
$("pyLink").onclick = (e) => { e.preventDefault(); window.wizard.openExternal("https://www.python.org/downloads/"); };

window.wizard.onLog((line) => { const l = $("log"); l.textContent += line + "\n"; l.scrollTop = l.scrollHeight; });
$("installBtn").onclick = async () => {
  $("installBtn").disabled = true; $("installStatus").textContent = "Installing…"; $("installStatus").className = "";
  try {
    await window.wizard.installEngine(sys.python.exe);
    installed = true; $("installStatus").textContent = "✔ Engine installed."; $("installStatus").className = "ok";
  } catch (e) {
    $("installStatus").textContent = "✖ " + e.message + " — check your internet connection and try again."; $("installStatus").className = "bad";
    $("installBtn").disabled = false;
  }
};

function collect() {
  const v = (id) => $(id).value.trim();
  const secretIds = ["POLYGON_API_KEY", "POLYGON_REALTIME", "FRED_API_KEY", "SEC_USER_AGENT", "ANTHROPIC_API_KEY",
    "ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET", "ETRADE_SANDBOX", "PLAID_CLIENT_ID", "PLAID_SECRET"];
  const secrets = Object.fromEntries(secretIds.map((k) => [k, v(k)]).filter(([, x]) => x));
  return {
    secrets,
    settings: { provider: v("provider"), paperCash: +v("paperCash"), username: v("username"), authMode: v("authMode"),
      riskLimits: { maxPositionValue: +v("maxPos"), maxPositionPct: +v("maxPct") / 100, maxExposurePct: +v("maxExp") / 100,
        dailyLossLimit: +v("dailyLoss"), maxOrdersPerDay: +v("maxOrders") },
      brokers: { paper: true, etrade: !!secrets.ETRADE_CONSUMER_KEY, chaseReadOnly: !!secrets.PLAID_CLIENT_ID }, liveTrading: false },
    security: { passcode: $("pass1").value },
  };
}

function summarize() {
  const c = collect().settings, r = c.riskLimits;
  $("summary").innerHTML = `<table>
    <tr><td>Data provider</td><td>${c.provider}</td></tr>
    <tr><td>Brokerage</td><td>Paper ($${c.paperCash.toLocaleString()})${c.brokers.etrade ? ", E*TRADE" : ""}${c.brokers.chaseReadOnly ? ", Chase (read-only)" : ""}</td></tr>
    <tr><td>Live trading</td><td>Disabled (enable in Settings after paper trading)</td></tr>
    <tr><td>Max position</td><td>$${r.maxPositionValue.toLocaleString()} / ${(r.maxPositionPct * 100).toFixed(0)}% of equity</td></tr>
    <tr><td>Daily loss limit</td><td>$${r.dailyLossLimit.toLocaleString()}</td></tr>
    <tr><td>Sign-in</td><td>${c.authMode} as ${c.username}</td></tr></table>`;
}

$("back").onclick = () => { if (i > 0) { i--; render(); } };
$("next").onclick = async () => {
  const gate = gates[sections[i].dataset.step];
  if (gate && !gate()) return;
  if (i < sections.length - 1) { i++; render(); return; }
  $("next").disabled = true; $("finishMsg").textContent = "Saving settings and starting the engine…";
  try { await window.wizard.finish(collect()); }
  catch (e) { $("finishMsg").textContent = "✖ " + e.message; $("finishMsg").className = "bad"; $("next").disabled = false; }
};

render();
