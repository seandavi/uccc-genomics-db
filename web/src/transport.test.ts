import { describe, expect, test } from "bun:test";
import { EMPTY } from "./cohort.ts";
import { TransportError, describeError, errorMessage, fetchAccount, fetchTransport, type FetchLike } from "./transport.ts";

interface Call { url: string; init: RequestInit }

function stub(status: number, body: unknown, headers: Record<string, string> = {}) {
  const calls: Call[] = [];
  const impl: FetchLike = async (url, init = {}) => {
    calls.push({url, init});
    return new Response(JSON.stringify(body), {status, headers: {"content-type": "application/json", ...headers}});
  };
  return {calls, transport: fetchTransport(impl)};
}

describe("requests", () => {
  test("count posts the definition to /api/cohort, same-origin", async () => {
    const {calls, transport} = stub(200, {patients: 120});
    await transport.count(EMPTY);
    expect(calls[0].url).toBe("/api/cohort");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.credentials).toBe("same-origin");
    expect((calls[0].init.headers as Record<string, string>)["content-type"]).toBe("application/json");
    expect(JSON.parse(calls[0].init.body as string)).toEqual(EMPTY);
  });
  test("apply posts {definition, op} to /api/apply; pivot to /api/pivot", async () => {
    const {calls, transport} = stub(200, {});
    const op = {op: "rename", name: "x"} as const;
    await transport.apply(EMPTY, op);
    await transport.pivot(EMPTY);
    expect(calls[0].url).toBe("/api/apply");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({definition: EMPTY, op});
    expect(calls[1].url).toBe("/api/pivot");
  });
  test("options is a GET that omits unset keys", async () => {
    const {calls, transport} = stub(200, {entries: []});
    await transport.options({q: "kras", limit: 5});
    expect(calls[0].url).toBe("/api/options?q=kras&limit=5");
    expect(calls[0].init.method).toBeUndefined();
    expect((calls[0].init.headers as Record<string, string>).accept).toBe("application/json");
    await transport.options({field: "alteration.aa", parent: "KRAS", q: undefined});
    expect(calls[1].url).toBe("/api/options?field=alteration.aa&parent=KRAS");
  });
});

describe("errors", () => {
  test("a 400 string detail", async () => {
    const {transport} = stub(400, {detail: "criteria.c1.gene: 'X' is not in the vocabulary"});
    const e = await transport.count(EMPTY).catch((x) => x);
    expect(e).toBeInstanceOf(TransportError);
    expect(e.message).toBe("criteria.c1.gene: 'X' is not in the vocabulary");
    expect(e.status).toBe(400);
  });
  test("a 422 list detail drops the body/query prefix", async () => {
    const {transport} = stub(422, {detail: [{loc: ["body", "criteria", 0, "gene"], msg: "Field required"}]});
    const e = await transport.count(EMPTY).catch((x) => x);
    expect(e.message).toBe("criteria.0.gene: Field required");
  });
  test("a 429 carries retry-after", async () => {
    const {transport} = stub(429, {detail: "rate limit"}, {"retry-after": "7"});
    const e = await transport.count(EMPTY).catch((x) => x);
    expect(e.status).toBe(429);
    expect(e.retryAfter).toBe(7);
  });
  test("a rejected fetch is status 0", async () => {
    const transport = fetchTransport(async () => { throw new TypeError("down"); });
    const e = await transport.count(EMPTY).catch((x) => x);
    expect(e).toBeInstanceOf(TransportError);
    expect(e.status).toBe(0);
    expect(e.message).toBe("network error");
  });
  test("an unrecognised body", () => {
    expect(errorMessage(500, null)).toBe("request failed (500)");
    expect(errorMessage(500, {detail: {x: 1}})).toBe("request failed (500)");
  });
});

describe("sign-in", () => {
  const signIns = (status: number, body: unknown) => {
    const seen: string[] = [];
    const transport = fetchTransport(async () => new Response(JSON.stringify(body), {status}), (l) => seen.push(l));
    return {seen, transport};
  };
  test("a 401 with a login path sends the user to sign in, and still throws", async () => {
    const {seen, transport} = signIns(401, {detail: "not signed in", login: "/auth/login"});
    const e = await transport.count(EMPTY).catch((x) => x);
    expect(seen).toEqual(["/auth/login"]);
    expect(e).toBeInstanceOf(TransportError);
    expect(e.status).toBe(401);
  });
  test("a 401 without one, or with an off-site one, does not", async () => {
    for (const body of [{detail: "bad credentials"}, {detail: "x", login: "https://evil.example/"}, {detail: "x", login: 1},
      {detail: "x", login: "//evil.example"}, {detail: "x", login: "/\\evil.example"},
      {detail: "x", login: "/\t/evil.example"}, {detail: "x", login: "/\n/evil.example"}]) {
      const {seen, transport} = signIns(401, body);
      await transport.count(EMPTY).catch(() => {});
      expect(seen).toEqual([]);
    }
  });
  test("other errors do not", async () => {
    const {seen, transport} = signIns(400, {detail: "bad", login: "/auth/login"});
    await transport.count(EMPTY).catch(() => {});
    expect(seen).toEqual([]);
  });
});

describe("account", () => {
  function account(status: number, body: unknown) {
    const calls: Call[] = [];
    const nav: string[] = [];
    const signIns: string[] = [];
    const impl: FetchLike = async (url, init = {}) => {
      calls.push({url, init});
      return new Response(JSON.stringify(body), {status});
    };
    return {calls, nav, signIns, account: fetchAccount(impl, (l) => signIns.push(l), (u) => nav.push(u))};
  }
  test("me is GET /api/me", async () => {
    const {calls, account: a} = account(200, {sub: "s", email: "a@example.edu", sign_out: true});
    expect(await a.me()).toEqual({sub: "s", email: "a@example.edu", sign_out: true});
    expect(calls[0].url).toBe("/api/me");
    expect(calls[0].init.method).toBeUndefined();
  });
  test("me on a 401 with a login path signs in", async () => {
    const {signIns, account: a} = account(401, {detail: "not signed in", login: "/auth/login"});
    await a.me().catch(() => {});
    expect(signIns).toEqual(["/auth/login"]);
  });
  test("signOut POSTs /auth/logout then navigates to the returned url", async () => {
    const {calls, nav, account: a} = account(200, {url: "https://id.example.test/end-session/"});
    await a.signOut();
    expect(calls[0].url).toBe("/auth/logout");
    expect(calls[0].init.method).toBe("POST");
    expect(nav).toEqual(["https://id.example.test/end-session/"]);
  });
});

describe("describeError", () => {
  test("401 and 429 keep their messages", () => {
    expect(describeError(new TransportError("x", 401))).toBe("Your login has expired; reload the page.");
    expect(describeError(new TransportError("x", 429, 7))).toBe("Too many queries; try again in 7 s.");
    expect(describeError(new TransportError("x", 429))).toBe("Too many queries; try again in a few s.");
    expect(describeError(new TransportError("bad field", 400))).toBe("bad field");
    expect(describeError(new Error("boom"))).toBe("boom");
  });
});
