"""Unit: the claims of the profile page (§F/administration/accounts/001120, 001121)."""

from __future__ import annotations

import jwt

from app.modules.auth.profile import TECHNICAL_CLAIMS, id_token_claims, person_claims


def _token(payload: dict[str, object]) -> str:
    return jwt.encode(payload, "secret-0123456789-0123456789-0123", algorithm="HS256")


def test_id_token_claims_reads_the_payload() -> None:
    assert id_token_claims(_token({"sub": "u1", "email": "a@x.de"})) == {
        "sub": "u1",
        "email": "a@x.de",
    }


def test_id_token_claims_without_or_with_a_broken_token_is_empty() -> None:
    assert id_token_claims(None) == {}
    assert id_token_claims("") == {}
    assert id_token_claims("not-a-jwt") == {}


def test_person_claims_hides_the_technical_claims_and_sorts() -> None:
    claims = {key: 1 for key in TECHNICAL_CLAIMS} | {
        "sub": "u1",
        "groups": ["a", "b"],
        "email_verified": True,
        "nickname": None,
    }
    assert person_claims(claims, sub="u1", email=None, name=None, groups=None) == [
        ("email_verified", True),
        ("groups", ["a", "b"]),
        ("sub", "u1"),
    ]


def test_person_claims_without_a_token_uses_the_stored_fields() -> None:
    assert person_claims({}, sub="u1", email="a@x.de", name=None, groups=None) == [
        ("email", "a@x.de"),
        ("groups", []),
        ("sub", "u1"),
    ]
