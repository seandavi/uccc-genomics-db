import { describe, expect, test } from "bun:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const css = readFileSync(join(import.meta.dir, "styles.css"), "utf8");
const ROOT = /:root\s*\{([^}]*)\}/g;
const tokens = (block: string): Record<string, string> =>
  Object.fromEntries([...block.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
const [light, dark] = [...css.matchAll(ROOT)].map((m) => tokens(m[1]));
const themes = { light, dark };

// WCAG 2.x relative luminance and contrast ratio for #rrggbb
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
const rule = (sel: string) =>
  css.match(new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "[^{]*\\{([^}]*)\\}"))?.[1] ?? "";

test("two :root blocks, light and dark", () => {
  expect([...css.matchAll(ROOT)].length).toBe(2);
});

test("no raw hex colour outside :root, in the CSS or in any source file", () => {
  expect(css.replace(ROOT, "")).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  const src = import.meta.dir;
  const files = readdirSync(src).filter((f) => /\.tsx?$/.test(f) && !/\.test\./.test(f) && f !== "api.gen.ts");
  expect(files.length).toBeGreaterThan(5);
  for (const f of files) expect([f, /#[0-9a-fA-F]{3,8}\b/.test(readFileSync(join(src, f), "utf8"))]).toEqual([f, false]);
});

test("every token used is defined, and every colour token has a dark value", () => {
  for (const m of css.matchAll(/var\((--[\w-]+)\)/g)) expect([m[1], m[1] in light]).toEqual([m[1], true]);
  for (const [k, v] of Object.entries(light)) if (/^#[0-9a-fA-F]{6}$/.test(v)) expect([k, k in dark]).toEqual([k, true]);
});

test("text pairs meet 4.5:1 in both themes", () => {
  const pairs = [
    ["--fg", "--bg"], ["--fg", "--surface"], ["--muted", "--bg"], ["--muted", "--surface"],
    ["--muted", "--surface-2"], ["--fg", "--surface-2"], ["--muted", "--suppressed-bg"], ["--accent-fg", "--accent"], ["--accent", "--bg"],
    ["--high", "--high-bg"], ["--moderate", "--moderate-bg"], ["--low", "--low-bg"], ["--danger", "--bg"],
  ];
  for (const [name, theme] of Object.entries(themes))
    for (const [a, b] of pairs) {
      const ratio = contrast(theme[a], theme[b]);
      expect([name, a, b, ratio >= 4.5]).toEqual([name, a, b, true]);
    }
});

test("the textarea is in the font: inherit rule", () => {
  expect(css.match(/([^{}]+)\{[^}]*font:\s*inherit/)?.[1]).toContain("textarea");
});

test("suppressed hatch is quiet", () => {
  expect(css).not.toContain("currentColor");
  for (const sel of [".vbar.hatched", "td.hatched"]) {
    expect(rule(sel)).toContain("var(--suppressed-stripe)");
    expect(rule(sel)).toContain("var(--suppressed-bg)");
  }
  expect(lum(dark["--suppressed-stripe"])).toBeLessThan(0.3);
});

describe("tier colours are semantic", () => {
  test("distinct from accent, bar and danger", () => {
    for (const theme of [light, dark]) {
      expect(theme["--moderate"]).not.toBe(theme["--accent"]);
      expect(theme["--moderate"]).not.toBe(theme["--bar"]);
      expect(theme["--low"]).not.toBe(theme["--danger"]);
    }
  });
  test("each tier rule uses its colour and tint", () => {
    for (const t of ["high", "moderate", "low"]) {
      expect(rule(`.tier-${t}`)).toContain(`var(--${t})`);
      expect(rule(`.tier-${t}`)).toContain(`var(--${t}-bg)`);
    }
  });
});

test("the patient count is the largest type", () => {
  expect(rule(".card.hero .big")).toContain("var(--fs-hero)");
  expect(rule(".big")).toContain("var(--fs-2xl)");
  expect(rule(".big")).toContain("tabular-nums");
  expect(rule(".barlabel")).toContain("tabular-nums");
  for (const [k, v] of Object.entries(light)) if (/^--fs-/.test(k) && k !== "--fs-hero") expect([k, parseInt(light["--fs-hero"]) > parseInt(v)]).toEqual([k, true]);
});

test("controls: sr-only, minimum heights and button classes", () => {
  const sr = rule(".sr-only");
  for (const p of ["margin: -1px", "padding: 0", "border: 0"]) expect(sr).toContain(p);
  expect(css).toContain("min-height: 36px");
  expect(css).toMatch(/@media \(pointer: coarse\)\s*\{[^@]*min-height: 44px/);
  for (const c of [".btn-primary", ".btn-secondary", ".btn-tertiary", ".btn-icon"]) expect(css).toContain(c);
});

test("two columns, centred", () => {
  expect(css).not.toContain(".assistant");
  expect(rule(".app")).toContain("max-width: 1280px");
  expect(rule(".app")).toContain("margin-inline: auto");
  expect(rule(".cols")).toContain("grid-template-columns: minmax(18rem, 22rem) 1fr;");
});

test("mobile shell: actions behind the more button, history on its own row, sticky summary bar", () => {
  const mobile = css.match(/@media \(max-width: 600px\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";
  expect(mobile).toContain(".actions { display: none; }");
  const inMobile = (sel: string) => mobile.match(new RegExp("\\n\\s*" + sel.replace(/\./g, "\\.") + " \\{([^}]*)\\}"))?.[1] ?? "";
  expect(inMobile(".more")).toContain("display: inline-flex");
  expect(inMobile(".history")).toContain("flex-basis: 100%");
  expect(inMobile(".card.hero")).toContain("grid-column: 1 / -1");
  expect(inMobile(".summary-bar")).toContain("position: sticky");
  expect(inMobile(".summary-bar")).toContain("bottom: 0");
  expect(css.replace(/@media \(max-width: 600px\)\s*\{[\s\S]*?\n\}/, "")).toContain(".summary-bar { display: none; }");
  expect(css.match(/([^{}]*)\{[^}]*suppressed-stripe\) 35%/)?.[1]).toContain(".summary-count.hatched");
});

test("builder: dashed adders, mode stripes, 24px chip buttons, no retired rules", () => {
  expect(rule(".adder")).toContain("dashed");
  expect(rule(".criterion.mode-include")).toContain("var(--high)");
  expect(rule(".criterion.mode-exclude")).toContain("var(--low)");
  expect(rule(".chip button")).toContain("min-height: 24px");
  expect(rule(".chip button")).toContain("min-width: 24px");
  expect(css).not.toContain(".cid");
  expect(css).not.toContain(".typeahead .field");
});
