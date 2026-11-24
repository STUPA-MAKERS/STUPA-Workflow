"""§ 001200: every API route of the backend has an MCP tool or a line in the exclusion list.

The test reads the backend routers and the tool modules as source (``ast``), so it needs
no backend dependencies. A route is a method and a path with each ``{parameter}`` written
as ``{}``. A tool calls a route when a tool module passes that path to ``api().get``,
``post``, ``put``, ``patch``, ``delete``, ``request`` or ``stream``, or to the
helpers of ``_download``/``_chat_files``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_MCP = Path(__file__).resolve().parents[1]
_BACKEND = _MCP.parents[1] / "backend" / "app"
_TOOLS = _MCP / "tools"
_METHODS = frozenset({"get", "post", "put", "patch", "delete", "websocket"})

#: § 001201: the routes that must not have a tool, with the reason of each group.
EXCLUDED: frozenset[tuple[str, str]] = frozenset(
    {
        # Casting a ballot, also as a guest (§ 000386), and the objection of a person.
        ("POST", "/votes/{}/ballot"),
        ("POST", "/votes/{}/objection"),
        ("POST", "/public/meetings/{}/votes/{}/ballot"),
        # Human-only permissions (§ 000462): backups, account merge, group revoke.
        ("GET", "/admin/backups"),
        ("POST", "/admin/backups"),
        ("POST", "/admin/backups/import"),
        ("GET", "/admin/backups/{}"),
        ("PATCH", "/admin/backups/{}"),
        ("DELETE", "/admin/backups/{}"),
        ("GET", "/admin/backups/{}/export"),
        ("POST", "/admin/backups/{}/restore"),
        ("GET", "/admin/principals/{}/merge-preview"),
        ("POST", "/admin/principals/{}/merge"),
        ("GET", "/admin/principals/{}/revoke-preview"),
        ("POST", "/admin/principals/{}/revoke"),
        # The run of a privacy erasure cannot be undone.
        ("POST", "/admin/privacy/erase-email"),
        ("POST", "/admin/privacy/principals/{}/erase"),
        ("POST", "/admin/privacy/erasures/{}/execute"),
        # The login lifetime: the server refuses every agent token.
        ("PUT", "/admin/login-settings"),
        # Paperless: no OAuth scope carries `admin.paperless`.
        ("GET", "/admin/paperless"),
        ("PUT", "/admin/paperless"),
        ("POST", "/admin/paperless/test"),
        ("GET", "/admin/paperless/failed-filings"),
        ("POST", "/admin/paperless/failed-filings/{}/retry"),
        ("POST", "/admin/paperless/backfill"),
        # A token does not copy documents into or out of Paperless (§ 002921).
        ("GET", "/paperless/insert"),
        ("GET", "/paperless/search"),
        ("POST", "/meetings/{}/documents/paperless"),
        ("POST", "/tickets/{}/files/{}/paperless"),
        # Ticket mail: no OAuth scope carries `admin.ticket_mail`.
        ("GET", "/admin/ticket-mailboxes"),
        ("POST", "/admin/ticket-areas/{}/mailbox"),
        ("PATCH", "/admin/ticket-areas/{}/mailbox"),
        ("DELETE", "/admin/ticket-areas/{}/mailbox"),
        ("POST", "/admin/ticket-areas/{}/mailbox/test"),
        # Login, logout, the OAuth flow and the MCP package: the MCP client does them.
        ("GET", "/auth/login"),
        ("GET", "/auth/callback"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/magic-link"),
        ("POST", "/auth/magic-link/verify"),
        ("POST", "/auth/email-login"),
        ("POST", "/auth/email-login/verify"),
        ("GET", "/oauth/authorize"),
        ("GET", "/oauth/consent-request"),
        ("POST", "/oauth/consent"),
        ("GET", "/oauth/finish"),
        ("POST", "/oauth/token"),
        ("GET", "/.well-known/oauth-authorization-server"),
        ("GET", "/.well-known/oauth-protected-resource"),
        ("GET", "/mcp/config"),
        ("GET", "/mcp/package"),
        ("GET", "/altcha/challenge"),
        # The applicant session (magic link) and the end link of an observer mail.
        ("GET", "/applicant/applications"),
        ("GET", "/applications/{}/applicant-transitions"),
        ("POST", "/applications/{}/applicant-transition"),
        ("POST", "/observers/end"),
        # Live channels, the tile read of a live ping and the calendar feeds with their token.
        ("WEBSOCKET", "/ws/meetings/{}"),
        ("WEBSOCKET", "/ws/meetings/{}/projector"),
        ("WEBSOCKET", "/ws/todos"),
        ("GET", "/todos/cards/{}/tile"),
        # A route that always refuses: an Event never becomes a to-do again.
        ("DELETE", "/todos/cards/{}/event"),
        ("WEBSOCKET", "/public/meetings/{}/ws"),
        ("GET", "/calendar/{}.ics"),
        ("GET", "/public/calendar.ics"),
        ("GET", "/calendar/me"),
        ("POST", "/calendar/me/rotate"),
        # The public pages without a login; a tool reads the same data with a login.
        ("GET", "/public/committees"),
        ("GET", "/public/decisions"),
        ("GET", "/public/protocols"),
        ("GET", "/public/protocols/semesters"),
        ("GET", "/public/protocols/{}"),
        ("GET", "/public/protocols/{}/pdf"),
        ("GET", "/public/protocols/{}/images/{}"),
        ("GET", "/public/protocols/{}/documents/{}"),
        ("GET", "/public/protocols/{}/documents/{}/info"),
        ("GET", "/public/calendar/entries"),
        ("GET", "/public/calendar/search"),
        ("GET", "/public/calendar/committees"),
        ("GET", "/public/calendar/meetings/{}"),
        ("GET", "/public/calendar/appointments/{}"),
        ("GET", "/public/meetings/{}"),
        ("POST", "/public/meetings/join/{}"),
        ("GET", "/public/meetings/{}/me"),
        ("PATCH", "/public/meetings/{}/me"),
        ("DELETE", "/public/meetings/{}/me"),
        # Browser assets: branding images, manifest, page head, texts, avatars, health.
        ("GET", "/branding/favicon"),
        ("GET", "/branding/icons/{}"),
        ("GET", "/branding/preview.png"),
        ("GET", "/manifest.webmanifest"),
        ("GET", "/page-head"),
        ("GET", "/site-config"),
        ("GET", "/i18n"),
        ("GET", "/principals/me/avatar"),
        ("GET", "/principals/{}/avatar"),
        ("GET", "/api/health"),
        # Web push of a browser: the key and the subscription come from the service worker,
        # and a push button acts through its own signed token.
        ("GET", "/push/key"),
        ("POST", "/push/devices"),
        ("GET", "/push/actions/{}"),
    }
)


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path).rstrip("/") or "/"


def _const_str(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
            for v in node.values
        )
    return None


def _prefixes(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", None) == "APIRouter"
        ):
            prefix = next(
                (_const_str(k.value) for k in node.value.keywords if k.arg == "prefix"), ""
            )
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = prefix or ""
    return out


def backend_routes() -> set[tuple[str, str]]:
    """Every (METHOD, path) that a backend router declares."""
    routes: set[tuple[str, str]] = set()
    for file in _BACKEND.rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        prefixes = _prefixes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for deco in node.decorator_list:
                if not (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in _METHODS
                    and isinstance(deco.func.value, ast.Name)
                    and deco.args
                ):
                    continue
                path = _const_str(deco.args[0])
                if path is None:
                    continue
                prefix = prefixes.get(deco.func.value.id, "")
                routes.add((deco.func.attr.upper(), _norm(prefix + path)))
    return routes


def tool_routes() -> set[tuple[str, str]]:
    """Every (METHOD, path) that a tool module sends."""
    calls: set[tuple[str, str]] = set()
    for file in _TOOLS.glob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if isinstance(func, ast.AsyncFunctionDef | ast.FunctionDef):
                calls |= _calls_of(func)
    return calls


def _branches(node: ast.expr) -> list[str]:
    """The texts that an expression can have: each branch of a conditional expression."""
    if isinstance(node, ast.IfExp):
        return _branches(node.body) + _branches(node.orelse)
    text = _const_str(node)
    return [] if text is None else [text]


def _calls_of(func: ast.AsyncFunctionDef | ast.FunctionDef) -> set[tuple[str, str]]:
    """The routes that one function sends; each value of a local path name counts."""
    names: dict[str, list[str]] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.setdefault(target.id, []).extend(_branches(node.value))

    def texts_of(node: ast.expr) -> list[str]:
        if isinstance(node, ast.Name):
            return names.get(node.id, [])
        return _branches(node)

    calls: set[tuple[str, str]] = set()
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute | ast.Name)):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        args = node.args
        if name in {"get", "post", "put", "patch", "delete"} and args:
            method, paths = name.upper(), texts_of(args[0])
        elif name in {"request", "stream", "download_to"} and len(args) >= 2:
            methods = texts_of(args[0])
            method, paths = (methods[0].upper() if methods else ""), texts_of(args[1])
        elif name == "post_message" and args:
            method, paths = "POST", texts_of(args[0])
        else:
            continue
        calls |= {(method, _norm(p.split("?")[0])) for p in paths if method and p.startswith("/")}
    return calls


def test_backend_routes_are_found() -> None:
    """The reader finds the routers; an empty set would pass every check below."""
    routes = backend_routes()
    assert ("GET", "/todos/boards") in routes
    assert ("POST", "/todos/cards/{}/checklist") in routes
    assert len(routes) > 300


@pytest.mark.parametrize("route", sorted(backend_routes()))
def test_route_has_tool_or_exclusion(route: tuple[str, str]) -> None:
    """§ 001200: a route has a tool, or § 001201 excludes it, never both."""
    called = route in tool_routes()
    excluded = route in EXCLUDED
    assert called != excluded, (
        f"{route}: {'excluded and called' if called else 'no tool and not excluded'}"
    )


def test_tools_call_routes() -> None:
    """Each path that a tool sends is a backend route, so a typo in a path fails here."""
    assert tool_routes() <= backend_routes()


def test_exclusions_are_routes() -> None:
    """§ 001201: each excluded route still exists, so the list stays exact."""
    assert backend_routes() >= EXCLUDED
