import { expect, test } from "bun:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const src = import.meta.dir;
const files = [
  ...readdirSync(src).filter((f) => !/\.test\./.test(f)).map((f) => join(src, f)),
  join(src, "..", "index.html"),
  join(src, "..", "discover.html"),
];
const text = (p: string) => readFileSync(p, "utf8");

test("the app has files to check", () => {
  expect(files.length).toBeGreaterThan(8);
});

test("no file names an external URL", () => {
  for (const f of files) expect([f, /https?:\/\//.test(text(f))]).toEqual([f, false]);
});

test("only transport.ts reaches the network, with relative /api/ URLs", () => {
  for (const f of files) {
    const t = text(f);
    const callsNetwork = /\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|EventSource/.test(t);
    expect([f, callsNetwork && !f.endsWith("transport.ts")]).toEqual([f, false]);
  }
  const t = text(join(src, "transport.ts"));
  expect(t).toContain('"/api/cohort"');
  expect(t).not.toMatch(/`https?:|"https?:/);
});

test("the browser never builds SQL", () => {
  for (const f of files) expect([f, /\bSELECT\s|\bFROM\s+mart|\.sql\b/.test(text(f))]).toEqual([f, false]);
});
