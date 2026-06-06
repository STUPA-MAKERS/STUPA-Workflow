"""TDD: serverseitige Altcha-Verifikation (security.md §7, Issue #23)."""

from __future__ import annotations

import base64
import json

import pytest

from app.shared.altcha import (
    AltchaError,
    AltchaVerifier,
    InMemoryReplayGuard,
    NullAltchaVerifier,
    RedisReplayGuard,
    create_challenge,
    encode_solution,
    solve_challenge,
    verify_solution,
)

SECRET = "altcha-test-secret-0123"


def _solved(*, expires: int | None = None, max_number: int = 50) -> str:
    challenge = create_challenge(SECRET, expires=expires, max_number=max_number)
    return solve_challenge(challenge)


# --------------------------------------------------------------------------- #
# verify_solution (reine Krypto)
# --------------------------------------------------------------------------- #
def test_valid_solution_round_trips() -> None:
    key = verify_solution(_solved(), SECRET, now=0)
    assert isinstance(key, str) and key


def test_create_challenge_with_fixed_number_is_solvable() -> None:
    challenge = create_challenge(SECRET, number=7, salt="abcd", max_number=10)
    assert verify_solution(encode_solution(challenge, 7), SECRET, now=0)


def test_wrong_secret_rejected() -> None:
    with pytest.raises(AltchaError):
        verify_solution(_solved(), "other-secret-01234567", now=0)


def test_malformed_base64_rejected() -> None:
    with pytest.raises(AltchaError):
        verify_solution("!!!not-base64!!!", SECRET, now=0)


def test_non_object_payload_rejected() -> None:
    payload = base64.b64encode(json.dumps([1, 2, 3]).encode()).decode()
    with pytest.raises(AltchaError):
        verify_solution(payload, SECRET, now=0)


def test_wrong_algorithm_rejected() -> None:
    challenge = create_challenge(SECRET, number=1, salt="s", max_number=2)
    payload = {
        "algorithm": "SHA-512",
        "challenge": challenge.challenge,
        "number": 1,
        "salt": challenge.salt,
        "signature": challenge.signature,
    }
    enc = base64.b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(AltchaError):
        verify_solution(enc, SECRET, now=0)


@pytest.mark.parametrize("number", [True, "5", 5.0, -1])
def test_invalid_number_type_rejected(number: object) -> None:
    challenge = create_challenge(SECRET, number=1, salt="s", max_number=2)
    payload = {
        "algorithm": "SHA-256",
        "challenge": challenge.challenge,
        "number": number,
        "salt": challenge.salt,
        "signature": challenge.signature,
    }
    enc = base64.b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(AltchaError):
        verify_solution(enc, SECRET, now=0)


def test_tampered_number_breaks_hash() -> None:
    challenge = create_challenge(SECRET, number=3, salt="s", max_number=10)
    # Andere Zahl → Hash passt nicht mehr zur Challenge.
    enc = encode_solution(challenge, 4)
    with pytest.raises(AltchaError):
        verify_solution(enc, SECRET, now=0)


def test_expired_challenge_rejected() -> None:
    enc = _solved(expires=100)
    with pytest.raises(AltchaError, match="expired"):
        verify_solution(enc, SECRET, now=101)


def test_not_yet_expired_accepted() -> None:
    enc = _solved(expires=100)
    assert verify_solution(enc, SECRET, now=100)


def test_missing_string_field_rejected() -> None:
    challenge = create_challenge(SECRET, number=1, salt="s", max_number=2)
    payload = {
        "algorithm": "SHA-256",
        "challenge": challenge.challenge,
        "number": 1,
        "salt": 123,  # kein String
        "signature": challenge.signature,
    }
    enc = base64.b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(AltchaError):
        verify_solution(enc, SECRET, now=0)


# --------------------------------------------------------------------------- #
# AltchaVerifier + Replay
# --------------------------------------------------------------------------- #
async def test_verifier_accepts_then_rejects_replay() -> None:
    verifier = AltchaVerifier(SECRET, replay=InMemoryReplayGuard(now=lambda: 0), now=lambda: 0)
    enc = _solved()
    await verifier.verify(enc)  # erste Nutzung ok
    with pytest.raises(AltchaError, match="already used"):
        await verifier.verify(enc)  # Replay


async def test_verifier_missing_solution_rejected() -> None:
    verifier = AltchaVerifier(SECRET, replay=InMemoryReplayGuard(), now=lambda: 0)
    with pytest.raises(AltchaError, match="required"):
        await verifier.verify(None)


async def test_null_verifier_passes_everything() -> None:
    verifier = NullAltchaVerifier()
    assert await verifier.verify(None) is None
    assert await verifier.verify("anything") is None


async def test_inmemory_replay_evicts_expired() -> None:
    clock = {"t": 0}
    guard = InMemoryReplayGuard(now=lambda: clock["t"])
    assert await guard.seen("k", ttl_seconds=10) is False
    assert await guard.seen("k", ttl_seconds=10) is True
    clock["t"] = 20  # über TTL → Eintrag geerntet
    assert await guard.seen("k", ttl_seconds=10) is False


class _FakeKV:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.fail = False

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if self.fail:
            raise RuntimeError("redis down")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


async def test_redis_replay_guard_detects_replay() -> None:
    guard = RedisReplayGuard(_FakeKV())
    assert await guard.seen("k", ttl_seconds=10) is False
    assert await guard.seen("k", ttl_seconds=10) is True


async def test_redis_replay_guard_falls_back_not_noop() -> None:
    kv = _FakeKV()
    kv.fail = True
    # Redis weg → NICHT no-op (sonst 300s replaybar, Review #1), sondern prozesslokaler
    # Fallback: Einmal-Nutzung gilt wenigstens pro Worker.
    guard = RedisReplayGuard(kv, fallback=InMemoryReplayGuard(now=lambda: 0))
    assert await guard.seen("k", ttl_seconds=10) is False
    assert await guard.seen("k", ttl_seconds=10) is True  # Replay erkannt
