import { describe, expect, it } from "vitest";
import { ApiError, apiFetch, detailOf, qs } from "./api";

function res(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status });
}

describe("apiFetch", () => {
  it("refreshes the session once on 401 and retries", async () => {
    const calls: string[] = [];
    let authed = false;
    const fetcher = async (url: string) => {
      calls.push(url);
      if (url === "/api/v1/auth/refresh") {
        authed = true;
        return res(200, { access_token: "x" });
      }
      return authed ? res(200, { ok: true }) : res(401, { detail: "not authenticated" });
    };
    await expect(apiFetch("/api/v1/dashboard", {}, fetcher)).resolves.toEqual({ ok: true });
    expect(calls).toEqual(["/api/v1/dashboard", "/api/v1/auth/refresh", "/api/v1/dashboard"]);
  });

  it("does not try to refresh for auth endpoints and surfaces the detail", async () => {
    const calls: string[] = [];
    const fetcher = async (url: string) => {
      calls.push(url);
      return res(401, { detail: "totp_required" });
    };
    const err = await apiFetch("/api/v1/auth/login", { method: "POST", json: {} }, fetcher).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).detail).toBe("totp_required");
    expect(calls).toEqual(["/api/v1/auth/login"]);
  });

  it("sends JSON with same-origin credentials and handles 204", async () => {
    let seen: RequestInit | undefined;
    const fetcher = async (_: string, init?: RequestInit) => {
      seen = init;
      return new Response(null, { status: 204 });
    };
    await expect(apiFetch("/api/v1/matches/seen", { method: "POST", json: { match_ids: ["a"] } }, fetcher)).resolves.toBeUndefined();
    expect(seen?.credentials).toBe("same-origin");
    expect(seen?.body).toBe('{"match_ids":["a"]}');
    expect((seen?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});

describe("detailOf", () => {
  it("reads FastAPI string and validation-list details", () => {
    expect(detailOf({ detail: "nope" }, "x")).toBe("nope");
    expect(detailOf({ detail: [{ msg: "weights must sum to 100" }, { msg: "bad" }] }, "x")).toBe("weights must sum to 100; bad");
    expect(detailOf(null, "fallback")).toBe("fallback");
  });
});

describe("qs", () => {
  it("drops empty values", () => {
    expect(qs({ a: 1, b: "", c: undefined, d: null, e: false, f: "x y" })).toBe("?a=1&e=false&f=x+y");
    expect(qs({})).toBe("");
  });
});
