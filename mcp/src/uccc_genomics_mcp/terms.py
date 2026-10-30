"""Portal terms: the Tier 1 gate (docs/specs/131-*.md, text from docs/HONEST_BROKER.md § "Portal terms").

A signed-in user who has not accepted TERMS_VERSION gets the terms page (a browser opening a page) or a 403
(/api/*, /mcp) from app.RequireUser. Acceptance is one row per (sub, terms_version) in Postgres. To change
the terms, edit TERMS_TEXT and bump TERMS_VERSION: everyone is asked again, and older rows stay as the
record. Holds staff `sub`s only, never patient data.
"""
import html
import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from starlette.responses import HTMLResponse

from uccc_genomics_mcp import authen, saved

TERMS_VERSION = "2026-10-30"
TERMS_TEXT = (
    "The clinical genomics portal contains de-identified, date-shifted data belonging to UCHealth and made "
    "available through the University of Colorado Cancer Center. Access is limited to approved cancer center "
    "members for research planning, feasibility, and cohort discovery. By using the portal, I agree not to "
    "attempt to identify any individual, link portal data with other sources to re-identify individuals, or "
    "share screenshots or exports beyond my study team. Identifiable data is available only through an "
    "approved honest-broker request tied to an active IRB authorization. Queries are logged.")
TERMS_REQUIRED = ("The portal terms have changed or have not been accepted. Reload this page (or open "
                  "/discover in a browser) to read and accept them.")
ACCEPT_PATH = "/api/terms/accept"
DEV_MODES = ("none", "password")

terms_acceptance = sa.Table(
    "terms_acceptance", saved.metadata,
    sa.Column("sub", sa.Text, primary_key=True),             # authen.User.sub
    sa.Column("terms_version", sa.Text, primary_key=True),
    sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

# ponytail: positive answers only, per process; an acceptance is never revoked and a bump changes the key.
# Grows by one entry per user per version.
_accepted: set[tuple[str, str]] = set()


def gate_on() -> bool:
    """False only for a development stand-in (--auth none|password) with no database: there is nowhere to
    record acceptance. main() refuses --auth access|authentik without DATABASE_URL."""
    return saved._engine is not None or authen.AUTH["mode"] not in DEV_MODES


async def accepted(sub: str) -> bool:
    """True if sub accepted the current TERMS_VERSION. saved.Unavailable without a database."""
    key = (sub, TERMS_VERSION)
    if key in _accepted:
        return True
    async with saved._begin() as conn:
        found = (await conn.execute(sa.select(terms_acceptance.c.sub).where(
            terms_acceptance.c.sub == sub, terms_acceptance.c.terms_version == TERMS_VERSION))).first()
    if found:
        _accepted.add(key)
    return found is not None


async def accept(sub: str) -> None:
    """Record that sub accepted the current TERMS_VERSION; accepting again keeps the first accepted_at."""
    async with saved._begin() as conn:
        await conn.execute(insert(terms_acceptance).values(sub=sub, terms_version=TERMS_VERSION)
                           .on_conflict_do_nothing())
    _accepted.add((sub, TERMS_VERSION))


_SCRIPT = """<script>
const error = document.getElementById("error");
async function detail(r, fallback) {
  try { return (await r.json()).detail || fallback; } catch { return fallback; }
}
document.getElementById("accept").onclick = async () => {
  try {
    const r = await fetch("/api/terms/accept", {method: "POST", credentials: "same-origin",
      headers: {"content-type": "application/json"}, body: JSON.stringify({version: %s})});
    if (r.ok) location.reload();
    else error.textContent = await detail(r, "Accepting failed; try again.");
  } catch { error.textContent = "Network error; try again."; }
};
const signOut = document.getElementById("sign-out");
if (signOut) signOut.onclick = async () => {
  try {
    const r = await fetch("/auth/logout", {method: "POST", credentials: "same-origin"});
    location.assign((await r.json()).url);
  } catch { error.textContent = "Sign-out failed; try again."; }
};
</script>"""


def page(sign_out: bool) -> HTMLResponse:
    """The full-page terms for a signed-in browser that hasn't accepted, served in place (status 403,
    Cache-Control: no-store). Accept POSTs JSON to ACCEPT_PATH and reloads, so the address and its #fragment
    stay. Sign out (authentik only) POSTs /auth/logout and goes to the returned url, as Discover does."""
    body = (authen._HEAD + "<h2>Portal terms</h2>"
            f"<p>{html.escape(TERMS_TEXT)}</p><p>Version {html.escape(TERMS_VERSION)}</p>"
            '<p>You need to accept these terms to use the portal.</p><p><button type="button" id="accept">I accept these terms</button>'
            + (' <button type="button" id="sign-out">Sign out</button>' if sign_out else "")
            + '</p><p id="error" role="alert"></p>'
            + _SCRIPT % json.dumps(TERMS_VERSION))
    return HTMLResponse(body, status_code=403, headers={"Cache-Control": "no-store"})
