"""Who is calling: `user(request) -> email`, or PermissionError. The backend is chosen once by `configure()`.

- `none`: local dev, everyone is dev@localhost.
- `password`: one local account over HTTP Basic (APP_USER, APP_PASSWORD_HASH in .env). A stand-in until
  Zitadel; it sends the password on every request, so use it on localhost or behind TLS only.
- `access`: a Cloudflare Access JWT, what production runs today.

Zitadel becomes another backend here; callers don't change.

    uv run python -m uccc_genomics_mcp.authen   # prompts for a password, prints APP_PASSWORD_HASH
"""
import base64
import getpass
import hashlib
import hmac
import os
import secrets

import jwt
from starlette.requests import Request

MODES = ("access", "password", "none")
AUTH = {"mode": "none", "team": None, "aud": None, "jwks": None, "user": None, "hash": None}


def configure(mode: str) -> None:
    """Set the backend from the environment; raises SystemExit naming what is missing."""
    if mode == "access":
        team, aud = os.environ.get("ACCESS_TEAM"), os.environ.get("ACCESS_AUD")
        if not (team and aud):
            raise SystemExit("--auth access needs ACCESS_TEAM and ACCESS_AUD (in .env)")
        AUTH.update(team=team, aud=aud, jwks=jwt.PyJWKClient(f"https://{team}.cloudflareaccess.com/cdn-cgi/access/certs"))
    elif mode == "password":
        name, h = os.environ.get("APP_USER"), os.environ.get("APP_PASSWORD_HASH")
        if not (name and h):
            raise SystemExit("--auth password needs APP_USER and APP_PASSWORD_HASH (in .env); "
                             "make the hash with `uv run python -m uccc_genomics_mcp.authen`")
        AUTH.update(user=name, hash=h)
    AUTH["mode"] = mode


def challenge() -> dict:
    """Headers for a 401, so a browser shows its login prompt under the password backend."""
    return {"WWW-Authenticate": 'Basic realm="uccc-genomics"'} if AUTH["mode"] == "password" else {}


def user(request: Request) -> str:
    if AUTH["mode"] == "none":
        return "dev@localhost"
    if AUTH["mode"] == "password":
        return _basic(request.headers.get("authorization", ""))
    return _access(request)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${_scrypt(password, salt).hex()}"


def _scrypt(password: str, salt: bytes) -> bytes:
    # ponytail: ~50 ms per request at these settings; fine for one local user, gone with Zitadel.
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def _basic(header: str) -> str:
    scheme, _, b64 = header.partition(" ")
    if scheme.lower() != "basic":
        raise PermissionError("missing credentials")
    try:
        name, _, password = base64.b64decode(b64, validate=True).decode().partition(":")
        _, salt, want = AUTH["hash"].split("$")
        ok = hmac.compare_digest(_scrypt(password, bytes.fromhex(salt)), bytes.fromhex(want))
    except ValueError:  # bad base64/utf-8 from the client, or a malformed hash in .env
        raise PermissionError("bad credentials")
    if not (ok and hmac.compare_digest(name, AUTH["user"])):
        raise PermissionError("bad credentials")
    return name


def _access(request: Request) -> str:
    # Access sends the same JWT as a header and as the CF_Authorization cookie; the Worker forwards both.
    token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
    if not token:
        raise PermissionError("missing Access token")
    try:
        key = AUTH["jwks"].get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=AUTH["aud"],
                            issuer=f"https://{AUTH['team']}.cloudflareaccess.com")
    except jwt.PyJWTError as e:
        raise PermissionError(str(e))
    return claims.get("email", "unknown")


if __name__ == "__main__":
    pw = getpass.getpass("password: ")
    if pw != getpass.getpass("again: "):
        raise SystemExit("passwords differ")
    print(f"APP_PASSWORD_HASH={hash_password(pw)}")
