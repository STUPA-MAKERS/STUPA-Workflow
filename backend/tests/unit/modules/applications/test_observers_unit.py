"""The pure rules of the observers of an application.

§ F/applications/applications/000751 only the applicant manages the observers; an
observer never does. § 000754 the end link carries ``<observer id>.<HMAC>`` and works
only with the right pepper.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.applications.access import Access
from app.modules.applications.observers import (
    END_PATH,
    can_manage_observers,
    end_link,
    end_token,
    observed_ids,
    parse_end_token,
)
from app.modules.auth.principal import Applicant, Principal

_APP = uuid.uuid4()
_SECRET = "magic-link-secret-for-the-tests"
_MEMBER = Principal(sub="m", roles=["member"], email="m@example.org")
_MANAGER = Principal(sub="x", roles=["member"], permissions={"application.manage"})


@pytest.mark.parametrize(
    ("access", "creator", "expected"),
    [
        (Access(_APP, _MEMBER, None, via="observer"), True, False),
        (Access(_APP, None, Applicant(email="a@example.org"), via="applicant"), False, True),
        (Access(_APP, _MEMBER, None, via="owner"), True, True),
        (Access(_APP, _MEMBER, None, via="committee"), False, False),
        (Access(_APP, _MANAGER, None), False, True),
        (Access(_APP, None, Applicant(email="o@example.org"), via="observer"), False, False),
    ],
)
def test_only_the_applicant_manages_the_observers(
    access: Access, creator: bool, expected: bool
) -> None:
    assert can_manage_observers(access, is_creator=creator) is expected


def test_the_end_token_checks_its_signature() -> None:
    observer_id = uuid.uuid4()
    token = end_token(_SECRET, observer_id)
    assert token.startswith(f"{observer_id}.")
    assert parse_end_token(_SECRET, token) == observer_id
    assert parse_end_token("another-secret-of-thirty-chars", token) is None
    assert parse_end_token(_SECRET, "kein-token") is None
    assert parse_end_token(_SECRET, f"{observer_id}") is None
    link = end_link("https://example.org/", _SECRET, observer_id)
    assert link == f"https://example.org{END_PATH}#t={token}"


async def test_no_address_observes_nothing() -> None:
    assert await observed_ids(None, None) == frozenset()  # type: ignore[arg-type]
    assert await observed_ids(None, "") == frozenset()  # type: ignore[arg-type]
