"""The pure rules of the Paperless integration (no database).

§ NF/security/network/002515 no OAuth scope carries a Paperless permission. § 002523 the
wait between two tries grows. § 002512 a part without a connection or with its switch
off is off.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.auth import oauth
from app.modules.auth.principal import Principal
from app.modules.paperless.connection import part_since
from app.modules.paperless.filings import MAX_TRIES, backoff
from app.modules.paperless.models import PaperlessSettings
from app.modules.paperless_filing.sources import application_title, open_kinds
from app.shared.permissions import PERMISSION_CATALOGUE

_SINCE = datetime(2026, 11, 1, tzinfo=UTC)


def _settings(**values: object) -> PaperlessSettings:
    base = {
        "base_url": "https://paperless.test",
        "token": "t",
        "file_protocols": False,
        "file_applications": False,
        "file_plans": False,
    }
    return PaperlessSettings(**{**base, **values})


def test_only_the_paperless_scope_carries_a_paperless_permission() -> None:
    """§F/integrations/mcp/002920: `paperless:use` alone carries it; the default asks for it."""
    assert {"admin.paperless", "paperless.use"} <= set(PERMISSION_CATALOGUE)
    carriers = {
        name for name, scope in oauth.SCOPES.items() if scope & {"admin.paperless", "paperless.use"}
    }
    assert carriers == {"paperless:use"}
    default = Principal(
        sub="agent",
        roles=["admin"],
        scope_permissions=oauth.scope_permissions(oauth.parse_scope(None)),
    )
    everything = Principal(
        sub="agent",
        roles=["admin"],
        scope_permissions=oauth.scope_permissions(list(oauth.SCOPES)),
    )
    assert default.has("paperless.use")
    assert not everything.has("admin.paperless")
    assert everything.has("paperless.use")


def test_the_wait_between_two_tries_doubles() -> None:
    assert backoff(1) == timedelta(minutes=1)
    assert backoff(2) == timedelta(minutes=2)
    assert backoff(MAX_TRIES - 1) == timedelta(minutes=64)
    assert backoff(0) == timedelta(minutes=1)


def test_a_part_is_on_only_with_its_switch_and_a_connection() -> None:
    on = _settings(file_protocols=True, protocols_since=_SINCE)
    assert part_since(on, "protocols") == _SINCE
    assert part_since(on, "applications") is None
    assert part_since(on, "plans") is None
    assert open_kinds(on) == ("protocol", "protocol_public", "ticket_file")

    without_token = _settings(token=None, file_protocols=True, protocols_since=_SINCE)
    assert part_since(without_token, "protocols") is None
    assert open_kinds(without_token) == ()

    every = _settings(
        file_protocols=True,
        protocols_since=_SINCE,
        file_applications=True,
        applications_since=_SINCE,
        file_plans=True,
        plans_since=_SINCE,
    )
    assert open_kinds(every) == (
        "protocol",
        "protocol_public",
        "application",
        "attachment",
        "plan",
        "ticket_file",
    )


def test_the_title_of_an_antrag_falls_back() -> None:
    assert application_title({"title": "  Plakate "}) == "Plakate"
    assert application_title({"title": " "}) == "Antrag"
    assert application_title({}) == "Antrag"
    assert application_title(None) == "Antrag"
