"""TDD: Magic-Link-Token-Primitive (security.md §1)."""

from __future__ import annotations

from app.modules.auth import tokens

PEPPER = "pepper-secret"


def test_generate_token_is_random_and_urlsafe() -> None:
    a = tokens.generate_token()
    b = tokens.generate_token()
    assert a != b
    assert len(a) >= 40
    # URL-sicher: kein +/= aus Standard-base64.
    assert set(a) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_hash_token_is_deterministic_32_bytes() -> None:
    t = tokens.generate_token()
    assert tokens.hash_token(t, PEPPER) == tokens.hash_token(t, PEPPER)
    assert len(tokens.hash_token(t, PEPPER)) == 32


def test_hash_token_depends_on_pepper() -> None:
    t = tokens.generate_token()
    assert tokens.hash_token(t, PEPPER) != tokens.hash_token(t, "other")


def test_verify_token_hash_roundtrip() -> None:
    t = tokens.generate_token()
    digest = tokens.hash_token(t, PEPPER)
    assert tokens.verify_token_hash(t, PEPPER, digest) is True


def test_verify_token_hash_rejects_wrong_token() -> None:
    digest = tokens.hash_token(tokens.generate_token(), PEPPER)
    assert tokens.verify_token_hash("not-the-token", PEPPER, digest) is False
