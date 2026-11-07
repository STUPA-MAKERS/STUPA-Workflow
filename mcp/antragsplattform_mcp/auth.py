"""OAuth2 browser-grant client (Authorization Code + PKCE, RFC 7636/8252).

This module is synchronous on purpose. It reaches the network through `httpx.Client` and
drives a browser plus a one-shot loopback HTTP server. The async API client calls
`ensure_access_token` in a worker thread. The module caches tokens on disk, one file per
platform URL, and refreshes them automatically. A failed refresh falls back to a fresh
browser login.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import SimpleQueue
from typing import Any
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


# Loopback hosts that may use cleartext http for local development (RFC 8252).
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _require_secure_base(base_url: str) -> None:
    """Reject a cleartext http:// base URL.

    OAuth codes and tokens must not travel in the clear. Only a loopback or development
    host may use http://.

    Raises:
        AuthError: The URL is not https:// and the host is not a loopback host.
    """
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


def _require_secure_endpoint(label: str, endpoint: str, base_url: str) -> None:
    """Check an endpoint from the discovery document again before use.

    An endpoint must pass the base scheme rule. It must also be same-origin with
    `base_url`. This stops a tampered discovery document from diverting the
    authorization code, the verifier or the tokens.

    Raises:
        AuthError: The endpoint is cleartext, or it is not same-origin with `base_url`.
    """
    _require_secure_base(endpoint)
    ep = urlparse(endpoint)
    base = urlparse(base_url)
    ep_origin = (ep.scheme.lower(), (ep.hostname or "").lower(), ep.port)
    base_origin = (base.scheme.lower(), (base.hostname or "").lower(), base.port)
    if ep_origin != base_origin:
        raise AuthError(
            f"OAuth {label} {endpoint!r} is not same-origin as the platform URL "
            f"{base_url!r}; refusing to send credentials cross-origin."
        )


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _discovery_attempt(url: str, base_url: str) -> dict | str:
    """Fetch the OAuth metadata at one URL.

    Returns:
        The checked metadata, or the text of the failure when the URL gives none.

    Raises:
        AuthError: The metadata lacks an endpoint or names an unsafe one.
    """
    try:
        resp = httpx.get(url, timeout=15)
    except httpx.HTTPError as exc:
        return str(exc)
    if resp.status_code != 200:
        return f"{resp.status_code} at {url}"
    try:
        meta = resp.json()
    except ValueError:
        return f"non-JSON response at {url}"
    # The metadata endpoints must be https (or loopback) and same-origin with
    # base_url before a browser redirect or a token POST uses them.
    for label in ("authorization_endpoint", "token_endpoint"):
        value = meta.get(label)
        if not isinstance(value, str) or not value:
            raise AuthError(f"OAuth discovery missing {label}")
        _require_secure_endpoint(label, value, base_url)
    return meta


def _discover(base_url: str) -> dict:
    # Reject a cleartext URL before any network call. Discovery returns the authorization
    # endpoint and the token endpoint. Both carry the OAuth code and the tokens.
    _require_secure_base(base_url)
    # Standard discovery sits at the root. Some deployments route only /api through the
    # edge proxy, so fall back to the metadata mirrored under /api.
    root = _discovery_attempt(f"{base_url}/.well-known/oauth-authorization-server", base_url)
    found = (
        root
        if isinstance(root, dict)
        else _discovery_attempt(f"{base_url}/api/.well-known/oauth-authorization-server", base_url)
    )
    if not isinstance(found, dict):
        raise AuthError(f"OAuth discovery failed: {found}")
    return found


class _CallbackServer(HTTPServer):
    """The loopback server of the callback. `timeout` bounds the wait for the one request."""

    timeout = _CALLBACK_TIMEOUT


def _capture_code(redirect_path: str) -> tuple[HTTPServer, SimpleQueue[dict]]:
    """Start a loopback server on a random port and return it with the queue of its result.

    The handler runs in the thread of the server, so it hands the callback parameters over
    through a queue.
    """
    results: SimpleQueue[dict] = SimpleQueue()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != redirect_path:
                self.send_response(404)
                self.end_headers()
                return
            q = parse_qs(parsed.query)
            results.put({key: (q.get(key) or [None])[0] for key in ("code", "state", "error")})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_DONE_HTML)

        def log_message(self, format: str, *args: object) -> None:
            # Keep the stdlib request log quiet.
            return

    return _CallbackServer(("127.0.0.1", 0), Handler), results


def browser_login(config: Config) -> dict:
    """Run the full browser grant, save the token to disk and return it."""
    meta = _discover(config.base_url)
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    server, results = _capture_code("/callback")
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

    # Serve exactly one request in a background thread. The timeout of the server bounds
    # the wait.
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    opened = webbrowser.open(auth_url)
    if not opened:
        print(f"Open this URL to log in:\n{auth_url}", flush=True)
    thread.join(timeout=_CALLBACK_TIMEOUT + 5)
    server.server_close()
    holder: dict = {} if results.empty() else results.get_nowait()

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
        raise AuthError(f"token endpoint error ({resp.status_code}): {_token_error(resp)}")
    tokens = resp.json()
    expires_in = tokens.get("expires_in")
    # An absent or null expires_in means the token does not expire. Only a revocation
    # ends it.
    return {
        **tokens,
        "expires_at": None if expires_in is None else time.time() + int(expires_in) - 60,
    }


def _token_error(resp: httpx.Response) -> Any:
    """Return the OAuth error text of a failed token response, or its raw text."""
    with contextlib.suppress(Exception):
        return resp.json().get("error_description") or resp.json().get("error")
    return resp.text


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
    # Create the token cache atomically with mode 0600 from the start. This leaves no
    # TOCTOU window where the secret is world-readable. A permission failure must surface.
    payload = json.dumps(tokens).encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def ensure_access_token(config: Config, *, force_login: bool = False) -> str:
    """Return a valid access token: from the cache, from a refresh, or from a new login."""
    tokens = None if force_login else _load(config)
    if tokens and tokens.get("access_token"):
        expires_at = tokens.get("expires_at", 0)
        # An expires_at of None means the token does not expire. Otherwise honor the deadline.
        if expires_at is None or expires_at > time.time():
            return tokens["access_token"]
    if tokens and tokens.get("refresh_token"):
        try:
            return _refresh(config, tokens["refresh_token"])["access_token"]
        except AuthError:
            pass  # the refresh token expired or is revoked: fall through to a fresh login
    return browser_login(config)["access_token"]


def logout(config: Config) -> bool:
    """Delete the cached token so the next call starts a new browser login.

    Returns:
        True if a cached token existed.
    """
    path = config.token_path()
    if path.exists():
        path.unlink()
        return True
    return False
