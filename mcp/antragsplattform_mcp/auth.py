"""OAuth2 browser-grant client (Authorization Code + PKCE, RFC 7636/8252).

Synchronous on purpose (network via ``httpx.Client``, browser + a one-shot loopback
HTTP server); the async API client calls :func:`ensure_access_token` via a worker thread.
Tokens are cached on disk per platform URL and refreshed automatically; a failed refresh
falls back to a fresh browser login.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .config import CLIENT_ID, Config

_CALLBACK_TIMEOUT = 300  # seconds to wait for the browser redirect

_DONE_HTML = (
    b"<!doctype html><html><body style='font-family:sans-serif;padding:3rem'>"
    b"<h2>Login complete</h2><p>You can close this tab and return to your agent.</p>"
    b"</body></html>"
)


class AuthError(RuntimeError):
    pass


# Loopback hosts where cleartext http is tolerated for local dev (RFC 8252 §8.3).
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _require_secure_base(base_url: str) -> None:
    """Reject cleartext http:// base URLs — OAuth code/tokens must not transit in the
    clear. http:// is allowed ONLY for explicit loopback/dev (localhost/127.0.0.1/[::1]);
    everything else MUST be https://. Apply before any discovery/token request."""
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host in _LOOPBACK_HOSTS:
        return
    raise AuthError(
        f"Insecure platform URL {base_url!r}: OAuth requires https:// "
        "(http:// is allowed only for loopback/dev: localhost, 127.0.0.1, [::1])."
    )


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _discover(base_url: str) -> dict:
    # Reject cleartext URLs before any network call — discovery + the endpoints it yields
    # (authorization/token) carry the OAuth code and tokens.
    _require_secure_base(base_url)
    # Standard discovery is at the root; some deployments only route /api through the
    # edge proxy, so fall back to the /api-mirrored metadata.
    candidates = [
        f"{base_url}/.well-known/oauth-authorization-server",
        f"{base_url}/api/.well-known/oauth-authorization-server",
    ]
    last = ""
    for url in candidates:
        try:
            resp = httpx.get(url, timeout=15)
        except httpx.HTTPError as exc:
            last = str(exc)
            continue
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                last = f"non-JSON response at {url}"
                continue
        last = f"{resp.status_code} at {url}"
    raise AuthError(f"OAuth discovery failed: {last}")


def _capture_code(redirect_path: str) -> tuple[HTTPServer, dict]:
    """Start a loopback server on a random port; return (server, result-holder)."""
    holder: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != redirect_path:
                self.send_response(404)
                self.end_headers()
                return
            q = parse_qs(parsed.query)
            holder["code"] = (q.get("code") or [None])[0]
            holder["state"] = (q.get("state") or [None])[0]
            holder["error"] = (q.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_DONE_HTML)

        def log_message(self, *_args) -> None:  # silence stdlib logging
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    return server, holder


def browser_login(config: Config) -> dict:
    """Run the full browser grant; return the token dict (and persist it)."""
    meta = _discover(config.base_url)
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    server, holder = _capture_code("/callback")
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    auth_url = meta["authorization_endpoint"] + "?" + urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": config.scope,
            "state": state,
        }
    )

    # Serve exactly one request, bounded by a timeout, in a background thread.
    server.timeout = _CALLBACK_TIMEOUT
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    opened = webbrowser.open(auth_url)
    if not opened:
        print(f"Open this URL to log in:\n{auth_url}", flush=True)
    thread.join(timeout=_CALLBACK_TIMEOUT + 5)
    server.server_close()

    if holder.get("error"):
        raise AuthError(f"authorization failed: {holder['error']}")
    if not holder.get("code"):
        raise AuthError("timed out waiting for the browser login callback")
    if holder.get("state") != state:
        raise AuthError("state mismatch (possible CSRF) — aborting")

    tokens = _exchange(
        meta["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": holder["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": CLIENT_ID,
        },
    )
    _save(config, tokens)
    return tokens


def _exchange(token_endpoint: str, data: dict) -> dict:
    resp = httpx.post(token_endpoint, data=data, timeout=15)
    if resp.status_code != 200:
        detail = resp.text
        try:
            detail = resp.json().get("error_description") or resp.json().get("error")
        except Exception:  # noqa: BLE001
            pass
        raise AuthError(f"token endpoint error ({resp.status_code}): {detail}")
    tokens = resp.json()
    expires_in = tokens.get("expires_in")
    # ``expires_in: null`` (or absent) means a non-expiring token — only revocation ends it.
    tokens["expires_at"] = None if expires_in is None else time.time() + int(expires_in) - 60
    return tokens


def _refresh(config: Config, refresh_token: str) -> dict:
    meta = _discover(config.base_url)
    tokens = _exchange(
        meta["token_endpoint"],
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
    )
    _save(config, tokens)
    return tokens


def _load(config: Config) -> dict | None:
    path = config.token_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _save(config: Config, tokens: dict) -> None:
    path = config.token_path()
    # Atomically create the cache file mode 0600 from the start (no TOCTOU window where the
    # secret is world-readable under the prevailing umask). Write to a sibling temp file and
    # os.replace into place; permission failures on the secret MUST NOT be swallowed.
    payload = json.dumps(tokens).encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ensure_access_token(config: Config, *, force_login: bool = False) -> str:
    """Return a valid access token: cached → refreshed → fresh browser login."""
    tokens = None if force_login else _load(config)
    if tokens and tokens.get("access_token"):
        expires_at = tokens.get("expires_at", 0)
        # ``expires_at is None`` → non-expiring token; otherwise honour the deadline.
        if expires_at is None or expires_at > time.time():
            return tokens["access_token"]
    if tokens and tokens.get("refresh_token"):
        try:
            return _refresh(config, tokens["refresh_token"])["access_token"]
        except AuthError:
            pass  # refresh expired/revoked → fall through to a fresh login
    return browser_login(config)["access_token"]


def logout(config: Config) -> bool:
    """Drop the cached token (next call triggers a fresh browser login)."""
    path = config.token_path()
    if path.exists():
        path.unlink()
        return True
    return False
