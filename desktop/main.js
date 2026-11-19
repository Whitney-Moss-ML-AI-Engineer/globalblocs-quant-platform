// GlobalBLOCS Quant desktop shell.
// First launch -> Setup Wizard (system check, engine install, data keys, brokerage, risk limits, passcode).
// Later launches -> start the local Python engine, wait for /health, open the dashboard.
const { app, BrowserWindow, ipcMain, safeStorage, shell, dialog, protocol, net } = require("electron");
const { pathToFileURL } = require("url");
const { spawn, execFile } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const http = require("http");

const USER = app.getPath("userData");
const CONFIG = path.join(USER, "config.json");
const SECRETS = path.join(USER, "secrets.bin");      // encrypted with the OS keychain via safeStorage
const VENV = path.join(USER, "engine-venv");
const RES = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..");
const ENGINE = app.isPackaged ? path.join(RES, "engine") : RES;
const WEB = app.isPackaged ? path.join(RES, "web") : path.join(RES, "frontend", "out");
const PORT = 8765;
let engine = null;
let win = null;

// Serve the static dashboard over a privileged app:// scheme so absolute /_next/ asset paths resolve.
protocol.registerSchemesAsPrivileged([{ scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: true } }]);

const venvPython = () => process.platform === "win32" ? path.join(VENV, "Scripts", "python.exe") : path.join(VENV, "bin", "python");
const readJSON = (p, d) => { try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return d; } };

function saveSecrets(obj) {
  if (!safeStorage.isEncryptionAvailable()) throw new Error("OS keychain encryption unavailable; cannot store secrets safely.");
  fs.writeFileSync(SECRETS, safeStorage.encryptString(JSON.stringify(obj)), { mode: 0o600 });
}
function loadSecrets() {
  try { return JSON.parse(safeStorage.decryptString(fs.readFileSync(SECRETS))); } catch { return {}; }
}

function findPython() {
  const candidates = process.platform === "win32" ? [["py", ["-3"]], ["python", []]] : [["python3", []], ["python", []]];
  return new Promise((resolve) => {
    const tryNext = (i) => {
      if (i >= candidates.length) return resolve(null);
      const [cmd, pre] = candidates[i];
      execFile(cmd, [...pre, "-c", "import sys;print(sys.version_info[0],sys.version_info[1],sys.executable)"], (err, out) => {
        if (err) return tryNext(i + 1);
        const [maj, min, exe] = out.trim().split(" ");
        if (+maj === 3 && +min >= 10) resolve({ version: `${maj}.${min}`, exe }); else tryNext(i + 1);
      });
    };
    tryNext(0);
  });
}

function run(cmd, args, onLine) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { cwd: ENGINE });
    const feed = (d) => d.toString().split(/\r?\n/).filter(Boolean).forEach(onLine);
    p.stdout.on("data", feed); p.stderr.on("data", feed);
    p.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`))));
  });
}

// ---------------- wizard IPC ----------------
ipcMain.handle("wizard:systemCheck", async () => {
  const py = await findPython();
  const free = fs.statfsSync ? (() => { const s = fs.statfsSync(USER); return Math.round((s.bavail * s.bsize) / 1e9); })() : null;
  return { python: py, freeDiskGB: free, platform: `${process.platform}-${process.arch}`, keychain: safeStorage.isEncryptionAvailable(),
           installDir: path.dirname(app.getPath("exe")), dataDir: USER };
});

ipcMain.handle("wizard:installEngine", async (evt, { pythonExe }) => {
  const send = (line) => evt.sender.send("wizard:log", line);
  send(`Creating isolated Python environment at ${VENV}`);
  await run(pythonExe, ["-m", "venv", VENV], send);
  await run(venvPython(), ["-m", "pip", "install", "--upgrade", "pip"], send);
  send("Installing quant engine dependencies (pandas, scikit-learn, FastAPI, ...). This can take several minutes.");
  await run(venvPython(), ["-m", "pip", "install", "-r", path.join(ENGINE, "requirements.txt")], send);
  send("Engine installed.");
  return true;
});

ipcMain.handle("wizard:openExternal", (_e, url) => shell.openExternal(url));

ipcMain.handle("wizard:finish", async (_e, cfg) => {
  const salt = crypto.randomBytes(16);
  const dk = crypto.pbkdf2Sync(cfg.security.passcode, salt, 600000, 32, "sha256");
  const secrets = {
    ...cfg.secrets,
    GB_ENCRYPTION_KEY: crypto.randomBytes(32).toString("base64").replace(/\+/g, "-").replace(/\//g, "_"),  // Fernet: url-safe base64 WITH padding
    JWT_SECRET: crypto.randomBytes(48).toString("base64url"),
    ADMIN_PASSWORD_HASH: `${salt.toString("hex")}$${dk.toString("hex")}`,
  };
  saveSecrets(secrets);
  fs.writeFileSync(CONFIG, JSON.stringify({ ...cfg.settings, configuredAt: new Date().toISOString(), version: app.getVersion() }, null, 2));
  await startEngineAndOpen();
  return true;
});

// ---------------- engine + dashboard ----------------
function engineEnv() {
  const c = readJSON(CONFIG, {});
  const s = loadSecrets();
  const r = c.riskLimits || {};
  return { ...process.env, ...s, PYTHONPATH: ENGINE, MARKET_DATA_PROVIDER: c.provider || "synthetic",
    LIVE_TRADING_ENABLED: "false", AUTH_DISABLED: c.authMode === "local-single-user" ? "true" : "false",
    ADMIN_USER: c.username || "admin", PAPER_CASH: String(c.paperCash || 100000),
    AUDIT_LOG: path.join(USER, "audit.jsonl"), CORS_ORIGINS: "app://gb",
    MOBILE_ACCESS: c.mobileAccess ? "true" : "false", ENGINE_PORT: String(PORT),
    PAIRED_DEVICES: path.join(USER, "devices.json"),
    MAX_POSITION_VALUE: String(r.maxPositionValue ?? 10000), MAX_POSITION_PCT: String(r.maxPositionPct ?? 0.1),
    MAX_EXPOSURE_PCT: String(r.maxExposurePct ?? 0.95), DAILY_LOSS_LIMIT: String(r.dailyLossLimit ?? 1000),
    MAX_ORDERS_PER_DAY: String(r.maxOrdersPerDay ?? 25) };
}

function waitHealthy(tries = 120) {
  return new Promise((resolve, reject) => {
    const ping = (n) => http.get(`http://127.0.0.1:${PORT}/health`, (r) => (r.statusCode === 200 ? resolve() : retry(n)))
      .on("error", () => retry(n));
    const retry = (n) => (n <= 0 ? reject(new Error("engine did not start")) : setTimeout(() => ping(n - 1), 500));
    ping(tries);
  });
}

async function startEngineAndOpen() {
  if (!engine) {
    // Phone access listens on the home network; otherwise the engine is reachable only from this computer.
    const host = readJSON(CONFIG, {}).mobileAccess ? "0.0.0.0" : "127.0.0.1";
    engine = spawn(venvPython(), ["-m", "uvicorn", "backend.app.main:app", "--host", host, "--port", String(PORT)],
      { cwd: USER, env: engineEnv() });
    engine.stderr.on("data", (d) => fs.appendFileSync(path.join(USER, "engine.log"), d));
    engine.on("exit", () => { engine = null; });
  }
  try { await waitHealthy(); } catch (e) {
    dialog.showErrorBox("Engine failed to start", `${e.message}\nSee ${path.join(USER, "engine.log")}`);
    return;
  }
  win.loadURL(`app://gb/index.html?api=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
}

function createWindow() {
  win = new BrowserWindow({ width: 1440, height: 900, minWidth: 1000, backgroundColor: "#0a1628", title: "GlobalBLOCS Quant",
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false } });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  if (fs.existsSync(CONFIG) && fs.existsSync(venvPython())) startEngineAndOpen();
  else win.loadFile(path.join(__dirname, "wizard", "index.html"));
}

app.whenReady().then(() => {
  protocol.handle("app", (req) => {
    const rel = decodeURIComponent(new URL(req.url).pathname).replace(/^\/+/, "") || "index.html";
    const file = path.normalize(path.join(WEB, rel));
    if (!file.startsWith(path.normalize(WEB))) return new Response("forbidden", { status: 403 });  // block path traversal
    const target = fs.existsSync(file) && fs.statSync(file).isDirectory() ? path.join(file, "index.html") : file;
    return net.fetch(pathToFileURL(target).toString());
  });
  createWindow();
});
app.on("window-all-closed", () => { if (engine) engine.kill(); app.quit(); });
