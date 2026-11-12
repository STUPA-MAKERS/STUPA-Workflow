"""The routes of each feature and the gate that closes them (§F/administration/admin/000757).

A route of a feature that is off answers 404 ``feature_disabled`` for every person and
every token, before the permission check of the route, so an admin gets the 404 too. The
table names the routes by the start of their path template. One table for all modules
keeps the rule in one place: a router file that holds the routes of two features, such as
the budget router with the invoices, needs no second router.
"""

from __future__ import annotations

import re
from typing import Final

from fastapi import WebSocketException
from starlette.requests import HTTPConnection

from app.deps import DbSession
from app.modules.auth.ws import WS_NOT_FOUND
from app.modules.site_config.features import Feature, FeatureDisabledError, active_features

#: The prefix of every API route, which the table leaves out.
API_PREFIX: Final = "/api"

_APPLICATION: Final = r"/applications/\{application_id\}"
_COMMITTEE: Final = r"/committees/\{gremium_id\}"

#: The path templates of each feature, as patterns that match the start of the template
#: behind ``/api``. A route that matches patterns of two features needs both: a vote in a
#: meeting needs `Sitzungen` and `Abstimmungen`.
ROUTE_PATTERNS: Final[tuple[tuple[Feature, re.Pattern[str]], ...]] = tuple(
    (feature, re.compile(rf"^(?:{pattern})(?:/|$|\.)"))
    for feature, pattern in (
        (Feature.TODOS, r"/todos"),
        (Feature.TODOS, r"/ws/todos"),
        (Feature.CALENDAR, r"/calendar"),
        (Feature.CALENDAR, r"/admin/calendars"),
        (Feature.CALENDAR, r"/public/calendar"),
        (Feature.MEETINGS, r"/meetings"),
        (Feature.MEETINGS, r"/ws/meetings"),
        (Feature.MEETINGS, r"/public/meetings"),
        (Feature.MEETINGS, r"/protocols"),
        (Feature.MEETINGS, r"/public/protocols"),
        (Feature.MEETINGS, r"/public/committees"),
        (Feature.MEETINGS, r"/delegations"),
        (Feature.MEETINGS, r"/admin/meeting-settings"),
        (Feature.MEETINGS, rf"{_COMMITTEE}/meeting-(?:defaults|members)"),
        (Feature.MEETINGS, rf"{_COMMITTEE}/(?:meetings|attendance)"),
        (Feature.VOTING, r"/votes"),
        (Feature.VOTING, rf"{_APPLICATION}/votes"),
        (Feature.VOTING, r"/meetings/\{meeting_id\}/votes"),
        (Feature.VOTING, r"/public/meetings/\{code\}/votes"),
        (Feature.VOTING, r"/protocols/\{protocol_id\}/votes"),
        (Feature.VOTING, r"/delegations/votes"),
        (Feature.VOTING, rf"{_COMMITTEE}/decisions"),
        (Feature.BUDGET, r"/budgets"),
        (Feature.BUDGET, r"/budget"),
        (Feature.BUDGET, r"/budget-expenses"),
        (Feature.BUDGET, r"/budget-transfers"),
        (Feature.BUDGET, r"/expenses"),
        (Feature.BUDGET, rf"{_APPLICATION}/(?:assign-budget|move-fiscal-year)"),
        (Feature.INVOICES, r"/invoices"),
        (Feature.TICKETS, r"/tickets"),
    )
)


def features_of_route(template: str) -> frozenset[Feature]:
    """Return the features that the route with this path template belongs to."""
    path = template.removeprefix(API_PREFIX)
    return frozenset(feature for feature, pattern in ROUTE_PATTERNS if pattern.match(path))


async def feature_gate(connection: HTTPConnection, db: DbSession) -> None:
    """Refuse a request to a route of a feature that is off.

    A route of no feature costs no read. A WebSocket closes with the code of "not
    found", because it has no HTTP answer after the handshake starts.

    Raises:
        FeatureDisabledError: A feature of the route is off (404 ``feature_disabled``).
        WebSocketException: The same for a WebSocket route.
    """
    needed = features_of_route(getattr(connection.scope.get("route"), "path", ""))
    off = needed - await active_features(db) if needed else frozenset[Feature]()
    if off and connection.scope["type"] == "websocket":
        raise WebSocketException(code=WS_NOT_FOUND)
    if off:
        raise FeatureDisabledError(off)
