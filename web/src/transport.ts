import type { ApplyResult, CountResult, Definition, Me, Operation, Options, PivotResult } from "./types.ts";

export interface OptionsQuery { q?: string; field?: string; parent?: string; limit?: number }

/** The one seam between the app and the cohort service. The MCP App will add a second implementation. */
export interface Transport {
  apply(definition: Definition, op: Operation): Promise<ApplyResult>;   // POST /api/apply   | MCP apply_op
  count(definition: Definition): Promise<CountResult>;                  // POST /api/cohort  | MCP count
  pivot(definition: Definition): Promise<PivotResult>;                  // POST /api/pivot   | MCP pivot
  options(query: OptionsQuery): Promise<Options>;                       // GET /api/options  | MCP search_vocabulary
}

export class TransportError extends Error {
  constructor(message: string, readonly status: number, readonly retryAfter: number | null = null) {
    super(message);
  }
}

/** FastAPI's {"detail": "..."} (400, 401, 429) or {"detail": [{loc, msg}]} (422). */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { loc?: (string | number)[]; msg?: string };
    if (Array.isArray(first?.loc) && typeof first.msg === "string") return `${first.loc.slice(1).join(".")}: ${first.msg}`;
  }
  return `request failed (${status})`;
}

/** The text a person sees for a failed request. */
export function describeError(e: unknown): string {
  if (e instanceof TransportError) {
    if (e.status === 401) return "Your login has expired; reload the page.";
    if (e.status === 429) return `Too many queries; try again in ${e.retryAfter ?? "a few"} s.`;
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** A same-site path: starts with "/", not "//" (protocol-relative), no backslash (browsers read "/\" as "//") and no control character (URL parsers drop tab and newline, so "/\t/host" is "//host"). */
export function sameSitePath(p: unknown): p is string {
  return typeof p === "string" && p.startsWith("/") && !p.startsWith("//") && !p.includes("\\") && !/[\u0000-\u001f\u007f]/.test(p);
}

/** Send the browser to sign in, back to this page afterwards (the fragment, e.g. a #d= share link, is kept). */
export function signInAt(login: string): void {
  window.location.assign(`${login}?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`);
}

function requester(fetchImpl: FetchLike, signIn: (login: string) => void) {
  return async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {accept: "application/json"};
    if (init.body !== undefined) headers["content-type"] = "application/json";
    let res: Response;
    try {
      res = await fetchImpl(path, {...init, headers, credentials: "same-origin"});
    } catch {
      throw new TransportError("network error", 0);
    }
    const body: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const login = (body as {login?: unknown} | null)?.login;
      if (res.status === 401 && sameSitePath(login)) signIn(login);
      const retry = res.status === 429 ? Number(res.headers.get("retry-after")) : NaN;
      throw new TransportError(errorMessage(res.status, body), res.status, Number.isFinite(retry) ? retry : null);
    }
    return body as T;
  };
}

export function fetchTransport(fetchImpl: FetchLike = fetch, signIn: (login: string) => void = signInAt): Transport {
  const request = requester(fetchImpl, signIn);
  const post = <T>(path: string, body: unknown) => request<T>(path, {method: "POST", body: JSON.stringify(body)});

  return {
    apply: (definition, op) => post("/api/apply", {definition, op}),
    count: (definition) => post("/api/cohort", definition),
    pivot: (definition) => post("/api/pivot", definition),
    options: (query) => {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) if (v !== undefined) p.set(k, String(v));
      return request(`/api/options?${p}`);
    },
  };
}

/** Who is signed in, and signing out. `sign_out` is false when the backend has no session to end. */
export interface Account {
  me(): Promise<Me>;         // GET /api/me
  signOut(): Promise<void>;  // POST /auth/logout, then the browser goes to the returned url
}

export function fetchAccount(fetchImpl: FetchLike = fetch, signIn: (login: string) => void = signInAt,
                             navigate: (url: string) => void = (u) => window.location.assign(u)): Account {
  const request = requester(fetchImpl, signIn);
  return {
    me: () => request("/api/me"),
    signOut: async () => navigate((await request<{url: string}>("/auth/logout", {method: "POST"})).url),
  };
}
