"""Every route of the app needs an auth dependency or a place on the public allowlist.

The test walks every route of ``create_app()`` and collects the callables of its
dependency tree: the route's own dependencies and the dependencies of every router
that includes it. A route passes when the tree holds one of the auth dependencies
(``AUTH_DEPENDENCIES``, or a closure of one of the ``AUTH_FACTORIES``). An optional
``get_current_principal`` counts, because the handler then decides with the
principal in hand. Any other route must be on ``PUBLIC_ROUTES``, so a new route
without auth fails here instead of going public by accident.

FastAPI includes a router lazily as ``_IncludedRouter``: its routes live in
``original_router.routes`` and its prefix and dependencies in ``include_context``.
The walk handles both shapes, so it also works with an eager include.

Groups of ``PUBLIC_ROUTES`` and why each one is public:

- FastAPI docs: the OpenAPI schema and the Swagger and ReDoc pages of the framework.
- Health: the container healthcheck and the smoke test call it without a session.
- Login: the OIDC login, the callback, the logout, the magic-link request (ALTCHA)
  and its verify run before a session exists.
- OAuth: ``authorize`` starts the PKCE grant, ``token`` authenticates the client by
  the code verifier or the refresh token, and the discovery documents (RFC 8414,
  RFC 9728) are public by spec, under ``/api`` and at the root.
- Public form: the apply wizard reads the form of an application type before login.
- Public meeting: guests join with the meeting code (ALTCHA) and then act with the
  guest cookie that the guest service checks: head, join, ``me``, ballot and the
  guest socket.
- Public protocols: the published protocols page with its Gremien, semesters,
  detail, PDF and images. The service shows public protocols only.
- Calendar: the ICS feed authenticates by the secret token in the path.
- ALTCHA: the challenge comes before every public write.
- Site config: the SPA reads branding and the PWA manifest before login.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any, Final

from fastapi import params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import BaseRoute, Route

from app.deps import (
    get_current_applicant,
    get_current_principal,
    require_any_permission,
    require_applicant,
    require_group,
    require_principal,
)
from app.main import create_app
from app.modules.livevote.router import get_ws_principal
from app.modules.todos.socket import get_todo_ws_principal

AUTH_DEPENDENCIES: Final[frozenset[Callable[..., Any]]] = frozenset(
    {get_current_principal, get_current_applicant, get_ws_principal, get_todo_ws_principal}
)
AUTH_FACTORIES: Final[tuple[Callable[..., Any], ...]] = (
    require_principal,
    require_any_permission,
    require_group,
    require_applicant,
)

PUBLIC_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
        ("GET", "/api/health"),
        ("GET", "/api/auth/login"),
        ("GET", "/api/auth/callback"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/magic-link"),
        ("POST", "/api/auth/magic-link/verify"),
        ("GET", "/api/oauth/authorize"),
        ("POST", "/api/oauth/token"),
        ("GET", "/api/.well-known/oauth-authorization-server"),
        ("GET", "/api/.well-known/oauth-protected-resource"),
        ("GET", "/.well-known/oauth-authorization-server"),
        ("GET", "/.well-known/oauth-protected-resource"),
        ("GET", "/api/application-types/{type_id}/form"),
        ("GET", "/api/public/meetings/{code}"),
        ("POST", "/api/public/meetings/join/{code}"),
        ("GET", "/api/public/meetings/{code}/me"),
        ("PATCH", "/api/public/meetings/{code}/me"),
        ("DELETE", "/api/public/meetings/{code}/me"),
        ("POST", "/api/public/meetings/{code}/votes/{vote_id}/ballot"),
        ("WS", "/api/public/meetings/{code}/ws"),
        ("GET", "/api/public/gremien"),
        ("GET", "/api/public/protocols"),
        ("GET", "/api/public/protocols/semesters"),
        ("GET", "/api/public/protocols/{protocol_id}"),
        ("GET", "/api/public/protocols/{protocol_id}/pdf"),
        ("GET", "/api/public/protocols/{protocol_id}/images/{image_id}"),
        ("GET", "/api/calendar/{token}.ics"),
        ("GET", "/api/altcha/challenge"),
        ("GET", "/api/site-config"),
        ("GET", "/api/manifest.webmanifest"),
    }
)


def _is_auth(call: Callable[..., Any]) -> bool:
    """Tell if a callable is an auth dependency or a closure of an auth factory."""
    if call in AUTH_DEPENDENCIES:
        return True
    qualname = getattr(call, "__qualname__", "")
    module = getattr(call, "__module__", "")
    return any(
        module == factory.__module__ and qualname.startswith(f"{factory.__qualname__}.<locals>.")
        for factory in AUTH_FACTORIES
    )


def _calls(dependant: Dependant, acc: set[Callable[..., Any]]) -> set[Callable[..., Any]]:
    for sub in dependant.dependencies:
        if sub.call is not None:
            acc.add(sub.call)
        _calls(sub, acc)
    return acc


def _router_calls(
    deps: Sequence[params.Depends], acc: set[Callable[..., Any]]
) -> set[Callable[..., Any]]:
    for dep in deps:
        if dep.dependency is not None:
            acc.add(dep.dependency)
            _calls(get_dependant(path="", call=dep.dependency), acc)
    return acc


def _walk(
    routes: Sequence[BaseRoute], prefix: str = "", deps: Sequence[params.Depends] = ()
) -> Iterator[tuple[str, str, set[Callable[..., Any]]]]:
    """Yield ``(method, path, dependency callables)`` for every route, recursively."""
    for route in routes:
        original = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if original is not None and context is not None:
            yield from _walk(
                original.routes,
                prefix + (context.prefix or ""),
                (*deps, *(context.dependencies or ()), *(original.dependencies or ())),
            )
        elif isinstance(route, APIRoute):
            calls = _router_calls(deps, _calls(route.dependant, set()))
            for method in sorted(route.methods or set()):
                yield method, prefix + route.path, calls
        elif isinstance(route, APIWebSocketRoute):
            yield "WS", prefix + route.path, _router_calls(deps, _calls(route.dependant, set()))
        elif isinstance(route, Route):
            for method in sorted((route.methods or set()) - {"HEAD"}):
                yield method, prefix + route.path, set()
        else:
            yield "ANY", prefix + str(getattr(route, "path", route)), set()


def _routes() -> list[tuple[str, str, set[Callable[..., Any]]]]:
    return list(_walk(create_app().router.routes))


def test_every_route_without_auth_is_on_the_public_allowlist() -> None:
    ungated = {
        (method, path)
        for method, path, calls in _routes()
        if not any(_is_auth(call) for call in calls)
    }
    assert sorted(ungated - PUBLIC_ROUTES) == [], "a route has no auth dependency"
    assert sorted(PUBLIC_ROUTES - ungated) == [], "an allowlist entry is gone or now gated"


def test_the_walk_reaches_the_lazily_included_routes() -> None:
    paths = {path for _method, path, _calls in _routes()}
    assert "/api/auth/me" in paths
    assert "/api/ws/todos" in paths


def test_is_auth_matches_factory_closures_only() -> None:
    assert _is_auth(require_principal("x"))
    assert _is_auth(require_applicant())
    assert _is_auth(get_ws_principal)
    assert not _is_auth(create_app)
