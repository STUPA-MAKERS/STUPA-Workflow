"""Server-side Altcha proof-of-work verification.

Altcha-compatible HMAC scheme: the server signs a PoW challenge with
``ALTCHA_HMAC_SECRET``; the client solves it (finds ``number`` with
``SHA-256(salt+number) == challenge``) and returns the base64 solution.
Verification is purely local (HMAC + hash recompute + expiry + one-time use); no
third party, no tracking.

``create_challenge``/``solve_challenge`` are symmetric (the latter is a reference
solver for tests/dev). ``verify_solution`` is pure and I/O-free; one-time use
(replay protection) lives in ``ReplayGuard`` and is orchestrated by ``AltchaVerifier``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Protocol, runtime_checkable
from urllib.parse import parse_qs, urlparse

from pydantic import AfterValidator

ALGORITHM = "SHA-256"


class AltchaError(Exception):
    """Invalid, missing, expired, or reused Altcha solution."""


@dataclass(frozen=True)
class Challenge:
    """Server-signed PoW challenge served to the client."""

    algorithm: str
    challenge: str
    salt: str
    signature: str
    maxnumber: int


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _hmac_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def create_challenge(
    secret: str,
    *,
    number: int | None = None,
    salt: str | None = None,
    expires: int | None = None,
    max_number: int = 100_000,
) -> Challenge:
    """Build a signed challenge; ``expires`` (unix seconds) is encoded into the salt."""
    base_salt = salt if salt is not None else secrets.token_hex(12)
    full_salt = f"{base_salt}?expires={expires}" if expires is not None else base_salt
    secret_number = number if number is not None else secrets.randbelow(max_number + 1)
    challenge = _sha256_hex(f"{full_salt}{secret_number}")
    return Challenge(
        algorithm=ALGORITHM,
        challenge=challenge,
        salt=full_salt,
        signature=_hmac_hex(secret, challenge),
        maxnumber=max_number,
    )


def encode_solution(challenge: Challenge, number: int) -> str:
    """Build the solution payload (base64 JSON), matching what altcha-lib sends."""
    payload = {
        "algorithm": challenge.algorithm,
        "challenge": challenge.challenge,
        "number": number,
        "salt": challenge.salt,
        "signature": challenge.signature,
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def solve_challenge(challenge: Challenge) -> str:
    """Reference solver (tests/dev): brute-forces ``number``, returns the base64 solution."""
    for number in range(challenge.maxnumber + 1):
        if _sha256_hex(f"{challenge.salt}{number}") == challenge.challenge:
            return encode_solution(challenge, number)
    raise ValueError("challenge unsolvable within maxnumber")  # pragma: no cover


def _parse_expires(salt: str) -> int | None:
    """Read ``expires`` seconds from the salt query (or None if absent/invalid)."""
    query = urlparse(f"//x?{salt.split('?', 1)[1]}").query if "?" in salt else ""
    if not query:
        return None
    raw = parse_qs(query).get("expires", [None])[0]
    if raw is None or not raw.isdigit():
        return None
    return int(raw)


@dataclass(frozen=True)
class Solution:
    """Structurally parsed (not yet cryptographically verified) PoW solution."""

    algorithm: str
    challenge: str
    number: int
    salt: str
    signature: str


def parse_solution(payload_b64: str) -> Solution:
    """Structurally parse the solution payload (base64 -> JSON -> required fields/types).

    Pure form validation without secret/crypto: checks that ``payload_b64`` is
    decodable base64 JSON with the expected fields and types. Raises ``AltchaError``
    on any structural invalidity. Used both by full verification and by early request
    validation so malformed input is rejected with 4xx regardless of the Altcha toggle."""
    try:
        raw = base64.b64decode(payload_b64, validate=True)
        data = json.loads(raw)
    except (binascii.Error, ValueError) as exc:
        raise AltchaError("malformed altcha payload") from exc
    if not isinstance(data, dict):
        raise AltchaError("malformed altcha payload")

    algorithm = data.get("algorithm")
    challenge = data.get("challenge")
    number = data.get("number")
    salt = data.get("salt")
    signature = data.get("signature")
    if algorithm != ALGORITHM:
        raise AltchaError("unsupported algorithm")
    if not (isinstance(challenge, str) and isinstance(salt, str) and isinstance(signature, str)):
        raise AltchaError("malformed altcha payload")
    # bool is an int subclass; exclude it explicitly. Negative numbers are invalid.
    if isinstance(number, bool) or not isinstance(number, int) or number < 0:
        raise AltchaError("malformed altcha payload")
    return Solution(
        algorithm=algorithm, challenge=challenge, number=number, salt=salt, signature=signature
    )


def validate_solution_format(value: str) -> str:
    """Pydantic ``AfterValidator``: structurally invalid Altcha -> ``ValueError`` (-> 422).

    Runs in the request schema before any endpoint logic and independent of whether
    Altcha verification is active, so a malformed payload is rejected consistently with
    problem+json 422 without touching enumeration protection (the rejection depends only
    on payload form). ``AltchaError`` is remapped to ``ValueError`` because Pydantic only
    turns ``ValueError``/``AssertionError`` into 422 (else 500)."""
    try:
        parse_solution(value)
    except AltchaError as exc:
        raise ValueError(f"malformed altcha solution: {exc}") from exc
    return value


AltchaSolutionStr = Annotated[str, AfterValidator(validate_solution_format)]
"""Request field type for an Altcha solution field: enforces structural form (422)."""


def verify_solution(payload_b64: str, secret: str, *, now: int) -> str:
    """Verify a solution (algorithm, hash, HMAC, expiry); return the replay key.

    Raises ``AltchaError`` on any invalidity. Constant-time compare for hash/HMAC.
    """
    parsed = parse_solution(payload_b64)
    challenge = parsed.challenge
    number = parsed.number
    salt = parsed.salt
    signature = parsed.signature

    expires = _parse_expires(salt)
    if expires is not None and now > expires:
        raise AltchaError("altcha challenge expired")
    if not hmac.compare_digest(_sha256_hex(f"{salt}{number}"), challenge):
        raise AltchaError("invalid altcha solution")
    if not hmac.compare_digest(_hmac_hex(secret, challenge), signature):
        raise AltchaError("invalid altcha signature")
    return signature


@runtime_checkable
class ReplayGuard(Protocol):
    """One-time use: True if the key was already seen within the window."""

    async def seen(self, key: str, ttl_seconds: int) -> bool: ...


class InMemoryReplayGuard:
    """Process-local replay protection (tests/single-worker dev)."""

    def __init__(self, *, now: Callable[[], int] | None = None) -> None:
        self._seen: dict[str, int] = {}
        self._now = now or _wall_clock

    async def seen(self, key: str, ttl_seconds: int) -> bool:
        now = self._now()
        # Reap expired entries so the store does not grow unbounded.
        self._seen = {k: exp for k, exp in self._seen.items() if exp > now}
        if key in self._seen:
            return True
        self._seen[key] = now + ttl_seconds
        return False


class RedisReplayGuard:
    """Redis-backed replay protection (SET NX + TTL), shared across workers.

    On Redis failure it does NOT fall back to a no-op (a solved PoW would be replayable
    within the TTL window); it falls back to a process-local ``InMemoryReplayGuard`` so
    one-time use still holds per worker (defense in depth). Rate limiting may fail open,
    replay protection must not."""

    def __init__(
        self,
        client: object,
        *,
        prefix: str = "altcha:seen:",
        fallback: ReplayGuard | None = None,
    ) -> None:
        self._client = client
        self._prefix = prefix
        self._fallback: ReplayGuard = fallback or InMemoryReplayGuard()

    async def seen(self, key: str, ttl_seconds: int) -> bool:
        # SET key 1 NX EX ttl -> None if already present (= replay).
        try:
            stored = await self._client.set(  # type: ignore[attr-defined]
                f"{self._prefix}{key}", "1", nx=True, ex=ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001 - Redis down -> process-local fallback
            logging.getLogger("app.altcha").warning(
                "altcha replay store unavailable, falling back to per-worker guard: %s",
                exc,
            )
            return await self._fallback.seen(key, ttl_seconds)
        return stored is None


def _wall_clock() -> int:
    import time

    return int(time.time())


class AltchaVerifier:
    """Verification plus replay protection; ``now`` is injectable (tests/expiry)."""

    def __init__(
        self,
        secret: str,
        *,
        replay: ReplayGuard,
        replay_ttl_seconds: int = 600,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._secret = secret
        self._replay = replay
        self._replay_ttl = replay_ttl_seconds
        self._now = now or _wall_clock

    async def verify(self, payload_b64: str | None) -> None:
        """Raise ``AltchaError`` if the solution is missing/invalid/expired/reused."""
        if not payload_b64:
            raise AltchaError("altcha solution required")
        key = verify_solution(payload_b64, self._secret, now=self._now())
        if await self._replay.seen(key, self._replay_ttl):
            raise AltchaError("altcha solution already used")


class NullAltchaVerifier:
    """No-op verifier (Altcha off: no secret configured, dev/test)."""

    async def verify(self, payload_b64: str | None) -> None:
        return None
