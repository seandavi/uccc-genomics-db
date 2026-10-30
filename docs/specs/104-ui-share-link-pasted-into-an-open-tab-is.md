# Spec #104: UI share link pasted into an open tab is ignored (handle hashchange)

Issue #104 is item 8 of the Discover UI/UX review (`docs/reviews/2026-10-30-discover-ux.md`, added
by the orchestrator). It changes `web/` only.

## Problem

`App.tsx` reads `window.location.hash` once, in the mount effect (`App.tsx:151-175`). Pasting or
following a share link (`#d=...`) into a tab where Discover is already open is a same-document
fragment navigation: the page does not reload, the mount effect does not run again, and the link is
ignored. The address bar then shows the pasted hash while the page shows the old cohort, so
Share copies a link to a cohort the page isn't showing.

## Goal

1. A `hashchange` to a share hash applies its definition through the same path as the initial
   load: `readShareHash`, then `transport.apply(decoded, {op: "rename", name})`, then
   `pushVersion` when the server's form differs from the current version. The answer is recounted.
2. An unreadable or server-rejected share hash shows the existing builder error
   "This link does not hold a valid cohort: …" and creates no version.
3. A hash equal to the current version's share hash (what `setHist` writes) creates no version
   and makes no request.
4. After any handled `hashchange`, the address bar holds the current version's share hash again
   (the invariant `setHist` keeps), so Share copies the cohort on screen.

## Non-goals

- **No output-path or data change.** Nothing under `src/uccc_genomics/`, `mcp/`, `dashboard/` or
  `systemd/` changes; no schema, table, column, endpoint or MCP tool changes. The pasted
  definition goes to the existing `POST /api/apply` (which validates it) and then the existing
  `POST /api/cohort`, so every number shown still passes the server's small-cell rule and renders
  through the same `Count` component. **`research_id` and `report_id` are not touched.**
- No change to the share-hash format (`shareHash` / `readShareHash` in `cohort.ts`), the
  definition or operations model, `transport.ts` or `api.gen.ts`.
- No `/c/<cohort_id>` links or saved cohorts (still #36).
- No `popstate` handling and no `pushState`: the app keeps writing the hash with `replaceState`.
- No new dependency (no DOM emulator such as happy-dom for tests): the logic is extracted into a
  function that the existing `bun test` + `renderToStaticMarkup` setup can call directly.

## Design

All code changes are in `web/src/App.tsx` and `web/src/app.test.tsx`, plus one sentence in
`dashboard/COHORT_DISCOVERY.md`.

### Why the app's own writes need a guard at all

`setHist` writes the hash with `window.history.replaceState`, which by the HTML spec never fires
`hashchange`. A `hashchange` still arrives with the app's own hash when the user goes Back/Forward
to a history entry whose URL `replaceState` already set to the current version's hash. The guard
(goal 3) compares the hash with `shareHash(current definition)` and returns before any request, so
that case is a no-op rather than a round trip.

### `web/src/App.tsx`: new exported function

The body of the mount effect's `if (window.location.hash.startsWith("#d="))` block moves into one
exported async function, used by both the mount effect and the new listener. It lives in `App.tsx`
(not `cohort.ts`, which holds pure helpers and does not import `transport.ts`) and is exported so
`app.test.tsx` can call it, as it already does for `FeasibilityPanel`, `SharePanel`,
`SummaryBar` and `Who`.

Imports: none new. `shareHash`, `readShareHash`, `pushVersion` and the `History` type already come
from `./cohort.ts`, `describeError` and the `Transport` type from `./transport.ts`, and
`Definition` from `./types.ts`.

```ts
/** What a URL hash does to the history. null: it is the current version's share hash (setHist wrote it),
 *  nothing to do. {history}: the history with the link's definition as a new version, or the history read
 *  after the request (unchanged) when the server's form equals the current version or the hash is not a
 *  share link. {error}: the text to show. history() is read again after the request, so an edit made
 *  meanwhile is kept. */
export async function applyShareHash(hash: string, history: () => History, transport: Pick<Transport, "apply">):
    Promise<{history: History} | {error: string} | null> {
  const before = history();
  if (hash === shareHash(before.versions[before.current].definition)) return null;
  if (!hash.startsWith("#d=")) return {history: before};
  try {
    const decoded = readShareHash(hash);
    if (decoded === null) throw new Error("it could not be read");
    const n = (decoded as {name?: unknown}).name;
    const r = await transport.apply(decoded as Definition, {op: "rename", name: typeof n === "string" ? n : ""});
    const h = history();
    return {history: JSON.stringify(r.definition) === JSON.stringify(h.versions[h.current].definition) ? h : pushVersion(h, r.definition)};
  } catch (e) {
    return {error: `This link does not hold a valid cohort: ${describeError(e)}`};
  }
}
```

The error text, the `rename` op (which makes the server validate and normalise the decoded
definition) and the JSON comparison are the ones the mount effect uses today, unchanged.

### `web/src/App.tsx`: mount effect

The `#d=` block in the mount effect becomes:

```ts
const loaded = await applyShareHash(window.location.hash, () => histRef.current, transport);
if (loaded && "error" in loaded) setEditError({at: "builder", message: loaded.error});
else if (loaded && "history" in loaded && loaded.history !== histRef.current) setHist(loaded.history);
```

The rest of the effect (options, `setHist(histRef.current)`, `refresh()`) is unchanged. One
behaviour change at mount, by design: a reload whose hash equals the stored current version's
share hash no longer re-sends that definition to `/api/apply` (it was a no-op request unless the
vocabulary changed; if it did, the count request that follows still reports the error in the
answer column).

### `web/src/App.tsx`: `hashchange` listener

A new effect, placed after the mount effect:

```ts
useEffect(() => {
  const onHashChange = async () => {
    const loaded = await applyShareHash(window.location.hash, () => histRef.current, transport);
    if (loaded === null) return;   // the app's own hash
    setEditError("error" in loaded ? {at: "builder", message: loaded.error} : null);
    setHist("history" in loaded ? loaded.history : histRef.current);   // the address bar shows the current version's share hash again
    refresh();
  };
  window.addEventListener("hashchange", onHashChange);
  return () => window.removeEventListener("hashchange", onHashChange);
}, [transport, setHist, refresh]);
```

- A valid link: a new version (n+1) with the server's form of the definition, the share hash
  rewritten, the error cleared and the answer recounted.
- A link equal to the current version after normalisation: no new version; the hash is rewritten
  to the canonical one; `refresh()` reuses the cached answer (same definition object).
- An invalid link: the builder error, no new version, and the hash restored to the current
  version's, so Share never copies the bad link.
- A non-share hash (for example `#answer-h` typed by hand, or an empty fragment): no version; the
  share hash is restored and any link error is cleared.

`setHist` already resets `copied`, writes local storage and updates the name input. No other state
changes. The effect does not need the StrictMode `started` guard: its cleanup removes the listener,
so a double run leaves one listener.

### `dashboard/COHORT_DISCOVERY.md`

In the Phase 1 paragraph, after "the share link carries the definition in the URL fragment (…)",
add: "Opening a share link in a tab where Discover is already open adds it as a new edit, as on
load." This records the behaviour; it contradicts nothing in the design sources.

## Acceptance criteria

- [ ] `applyShareHash` is exported from `web/src/App.tsx` with the signature above.
- [ ] A share hash for a definition other than the current one returns a history with one more
      version (`n` = last `n` + 1), `current` pointing at it, and the server's definition; `apply`
      is called once with `{op: "rename", name}`.
- [ ] An unreadable `#d=` hash returns `{error: "This link does not hold a valid cohort: it could
      not be read"}` without calling `apply`.
- [ ] A hash whose `apply` rejects (a `TransportError`) returns
      `{error: "This link does not hold a valid cohort: <describeError text>"}`.
- [ ] `shareHash(current definition)` returns `null` without calling `apply`.
- [ ] A link whose server form equals the current definition returns the same history object
      (`toBe`), no new version.
- [ ] A hash not starting with `#d=` returns the same history object without calling `apply`.
- [ ] The history is read after `apply` resolves: an edit pushed while the request is pending is
      kept, and the link's version is pushed after it.
- [ ] `App.tsx` adds a `hashchange` listener with `window.addEventListener` and removes it in the
      effect cleanup; the mount effect calls `applyShareHash` (one code path).
- [ ] `COHORT_DISCOVERY.md` Phase 1 paragraph has the sentence above.
- [ ] `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` passes; existing
      tests are unchanged.

Verified by the orchestrator on the dev server after merge (not by tests): with Discover open on
cohort A, pasting cohort B's share link into the address bar shows B as "Edit n+1" with B's
count; pasting a corrupted `#d=` shows the error and the address bar returns to B's hash.

## Test plan

All in `web/src/app.test.tsx`, a new `describe("applyShareHash")`. No network, no DOM: a fake
transport `{apply}` records its calls and resolves `{definition} as ApplyResult` (or rejects).
Definitions are synthetic, built from `EMPTY` (for example
`{...EMPTY, name: "b", population: {...EMPTY.population, sex: ["Female"]}}`).

1. **valid link adds a version.** `h = {versions: [{n: 1, definition: EMPTY}], current: 0}`;
   `applyShareHash(shareHash(b), () => h, echo)` → `history.versions.length === 2`,
   `current === 1`, `versions[1].n === 2`, `versions[1].definition` deep-equals `b`; one `apply`
   call with op `{op: "rename", name: "b"}`.
2. **unreadable hash.** `"#d=!!!"` → the "could not be read" error; zero `apply` calls.
3. **server rejects.** `apply` rejects with `new TransportError("criteria.0.gene: unknown", 422)`
   → `{error: "This link does not hold a valid cohort: criteria.0.gene: unknown"}`.
4. **own hash.** `shareHash(EMPTY)` with `h` above → `null`; zero `apply` calls.
5. **same after normalisation.** A link to `{...EMPTY, name: "x"}` whose fake `apply` resolves
   `EMPTY` → `result.history` is `h` (`toBe`).
6. **not a share hash.** `"#answer-h"` and `""` → `result.history` is `h`; zero `apply` calls.
7. **edit during the request.** The getter returns `h` before `apply` resolves and `h2 =
   pushVersion(h, c)` after → the result has three versions, `c` at n 2 and `b` at n 3.
8. **one code path (source test, like "the header source never mentions cohort_id").** The
   `App.tsx` source contains `addEventListener("hashchange"` and `removeEventListener("hashchange"`,
   contains `applyShareHash(window.location.hash` twice, and no longer contains
   `window.location.hash.startsWith`.

Checks: `cd web && bun install --frozen-lockfile && bun run typecheck && bun test`. `uv run pytest
-q` and the dashboard `npm test` are n/a (no Python or dashboard code changes), but run
`uv run pytest -q` once to confirm nothing else moved.

## Risks

- **Two pastes in quick succession** both resolve and push in resolve order; the last to resolve
  is current. Acceptable for a user action; no sequence guard is added.
- **A paste while an edit is in flight** pushes both versions; neither is lost, because both paths
  read `histRef.current` after their request.
- **The listener's `setHist` call on a non-share hash** clears a lingering link error. Harmless:
  the error described the previous paste.
- **Mount no longer re-validates the own hash** (see Mount effect). A definition that became
  invalid surfaces as the count error instead of the link error.
- **Behaviour is pinned through `applyShareHash` and a source test, not a DOM event.** The
  listener wiring itself (four lines) is checked by the orchestrator on the dev server.
