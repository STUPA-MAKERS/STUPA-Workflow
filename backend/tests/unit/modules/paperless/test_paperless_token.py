"""A token does not copy documents into or out of Paperless (§F/integrations/mcp/002921).

Each route refuses a token with the scope `paperless:use` before it touches a service,
so the stubs below are never called.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.deps import refuse_agent_token
from app.modules.auth import oauth
from app.modules.auth.principal import Principal
from app.modules.paperless.schemas import InsertIn
from app.modules.paperless_filing import router as paperless_router
from app.modules.protocol import documents_router
from app.modules.tickets import router as tickets_router
from app.shared.errors import ForbiddenError

_TOKEN = Principal(
    sub="agent",
    roles=["admin"],
    scope_permissions=oauth.scope_permissions(["read", "paperless:use", "meetings:write"]),
    grant={"id": "g", "client": "c"},
)


class _Untouched:
    """A dependency that fails the test when the route uses it."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the route used {name} before it refused the token")


def _refused(exc: pytest.ExceptionInfo[ForbiddenError]) -> None:
    assert exc.value.code == "cookie_session_required"


async def test_a_token_does_not_insert_or_file() -> None:
    """Insert state, search, copy into a protocol and ticket filing: 403 for a token."""
    stub: Any = _Untouched()
    with pytest.raises(ForbiddenError) as insert:
        await paperless_router.read_paperless_insert(user=_TOKEN, connection=stub)
    _refused(insert)
    with pytest.raises(ForbiddenError) as search:
        await paperless_router.search_paperless(user=_TOKEN, connection=stub, q="x")
    _refused(search)
    with pytest.raises(ForbiddenError) as copy:
        await documents_router.insert_paperless_document(
            meeting_id=uuid.uuid4(),
            data=InsertIn.model_validate({"documentId": 41}),
            protocols=stub,
            media=stub,
            principal=_TOKEN,
            session=stub,
            connection=stub,
        )
    _refused(copy)
    with pytest.raises(ForbiddenError) as filing:
        await tickets_router.file_ticket_file_in_paperless(
            ticket_id=uuid.uuid4(),
            attachment_id=uuid.uuid4(),
            service=stub,
            db=stub,
            worker=stub,
            user=_TOKEN,
        )
    _refused(filing)


async def test_a_person_without_the_permission_still_gets_the_plain_refusal() -> None:
    """A principal without `paperless.use` gets the 403 of the missing permission."""
    stub: Any = _Untouched()
    person = Principal(sub="p")
    with pytest.raises(ForbiddenError) as copy:
        await documents_router.insert_paperless_document(
            meeting_id=uuid.uuid4(),
            data=InsertIn.model_validate({"documentId": 41}),
            protocols=stub,
            media=stub,
            principal=person,
            session=stub,
            connection=stub,
        )
    assert copy.value.code != "cookie_session_required"


def test_a_session_cookie_passes_the_token_refusal() -> None:
    """`refuse_agent_token` lets a session cookie through and stops a token."""
    refuse_agent_token(Principal(sub="p", permissions={"paperless.use"}), "x")
    with pytest.raises(ForbiddenError) as exc:
        refuse_agent_token(_TOKEN, "x")
    _refused(exc)
