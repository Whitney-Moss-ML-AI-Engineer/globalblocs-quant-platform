// Where the dashboard finds the engine:
//  - Desktop app: the Electron shell injects window.GB_API (local engine).
//  - Phone app:   the server saved on the Connect screen (paired desktop over Wi-Fi, or a cloud URL).
//  - Browser:     NEXT_PUBLIC_API_URL or the local default.
const w = () => (typeof window !== "undefined" ? (window as any) : undefined);

export const isPhoneApp = () => !!w()?.Capacitor?.isNativePlatform?.();
export const isDesktopApp = () => !!w()?.GB_API;

export function apiBase(): string {
  return w()?.GB_API || (typeof localStorage !== "undefined" && localStorage.getItem("gb_server")) ||
    process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
}

export function getToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem("gb_token");
}

export function saveConnection(server: string | null, token: string | null) {
  if (server) localStorage.setItem("gb_server", server.replace(/\/+$/, ""));
  if (token) localStorage.setItem("gb_token", token); else localStorage.removeItem("gb_token");
}

export function disconnect() {
  localStorage.removeItem("gb_token");
  if (!isDesktopApp()) localStorage.removeItem("gb_server");
}

export class AuthError extends Error {}

export async function api<T = any>(path: string, init?: RequestInit, base?: string): Promise<T> {
  const token = getToken();
  const res = await fetch(`${base || apiBase()}${path}`, { ...init, headers: { "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init?.headers || {}) } });
  if (res.status === 401) {
    if (typeof window !== "undefined") window.dispatchEvent(new Event("gb-auth-required"));
    throw new AuthError(await res.text());
  }
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export async function signIn(server: string, username: string, password: string) {
  const body = new URLSearchParams({ username, password });
  const res = await fetch(`${server}/auth/token`, { method: "POST", body,
    headers: { "Content-Type": "application/x-www-form-urlencoded" } });
  if (!res.ok) throw new Error(res.status === 401 ? "Wrong username or passcode" : `Sign-in failed (${res.status})`);
  saveConnection(server, (await res.json()).access_token);
}

export async function pairWithDesktop(server: string, code: string, deviceName: string) {
  const health = await fetch(`${server}/health`).then(r => r.json()).catch(() => null);
  if (health?.app !== "globalblocs-quant") throw new Error("No GlobalBLOCS desktop found at that address. Check the address and that both devices are on the same Wi-Fi.");
  const res = await fetch(`${server}/pairing/claim`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, device_name: deviceName }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Pairing failed (${res.status})`);
  saveConnection(server, (await res.json()).access_token);
}

export const pct = (x?: number | null, d = 1) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
export const usd = (x?: number | null) => (x == null ? "—" : x.toLocaleString("en-US", { style: "currency", currency: "USD" }));
