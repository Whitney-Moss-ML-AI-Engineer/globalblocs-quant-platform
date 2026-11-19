export const API = (typeof window !== "undefined" && (window as any).GB_API) || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? sessionStorage.getItem("gb_token") : null;
  const res = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init?.headers || {}) } });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}
export const pct = (x?: number | null, d = 1) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
export const usd = (x?: number | null) => (x == null ? "—" : x.toLocaleString("en-US", { style: "currency", currency: "USD" }));
