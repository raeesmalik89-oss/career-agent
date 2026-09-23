// Thin fetch wrapper. Auth lives in httpOnly cookies set by the backend, so nothing here stores tokens.

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

let refreshing: Promise<boolean> | null = null;

/** One refresh at a time: concurrent 401s wait for the same refresh call. */
async function refreshSession(fetcher: FetchLike): Promise<boolean> {
  refreshing ??= fetcher("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : String(e)))
        .join("; ");
    }
  }
  return fallback;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
  fetcher: FetchLike = fetch,
): Promise<T> {
  const { json, headers, ...rest } = init;
  const req: RequestInit = {
    ...rest,
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  };
  let res = await fetcher(path, req);
  if (res.status === 401 && !path.startsWith("/api/v1/auth/")) {
    if (await refreshSession(fetcher)) res = await fetcher(path, req);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailOf(body, res.statusText || `HTTP ${res.status}`));
  return body as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, json?: unknown) => apiFetch<T>(path, { method: "POST", json: json ?? {} }),
  put: <T>(path: string, json: unknown) => apiFetch<T>(path, { method: "PUT", json }),
  patch: <T>(path: string, json: unknown) => apiFetch<T>(path, { method: "PATCH", json }),
};

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}
