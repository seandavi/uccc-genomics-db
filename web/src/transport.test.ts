import { describe, expect, test } from "bun:test";
import { EMPTY } from "./cohort.ts";
import { TransportError, errorMessage, fetchTransport, type FetchLike } from "./transport.ts";

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
