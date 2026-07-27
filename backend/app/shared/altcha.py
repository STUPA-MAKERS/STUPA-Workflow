"""Server-side ALTCHA proof-of-work verification.

The HMAC scheme follows ALTCHA. The server signs a proof-of-work challenge with
``ALTCHA_HMAC_SECRET``. The client solves it. It looks for the ``number`` where
``SHA-256(salt+number) == challenge``, then returns the base64 solution. Verification
stays local: HMAC, hash recompute, expiry and one-time use. No third party takes part,
and nothing tracks the user.

``create_challenge`` and ``solve_challenge`` are symmetric. ``solve_challenge`` is a
reference solver for tests and development. ``verify_solution`` is pure and does no
I/O. ``ReplayGuard`` holds the one-time-use state, and ``AltchaVerifier`` orchestrates
both parts.
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
    """The ALTCHA solution is missing, invalid, expired, or already used."""


@dataclass(frozen=True)
class Challenge:
    """A server-signed proof-of-work challenge for the client."""

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
    """Build a signed challenge.

    The salt encodes ``expires`` as unix seconds.
    """
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
    """Build the base64 JSON solution payload that altcha-lib sends."""
    payload = {
        "algorithm": challenge.algorithm,
        "challenge": challenge.challenge,
        "number": number,
        "salt": challenge.salt,
        "signature": challenge.signature,
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def solve_challenge(challenge: Challenge) -> str:
    """Solve a challenge by brute force and return the base64 solution.

    This is a reference solver for tests and development.
    """
    for number in range(challenge.maxnumber + 1):
        if _sha256_hex(f"{challenge.salt}{number}") == challenge.challenge:
            return encode_solution(challenge, number)
    raise ValueError("challenge unsolvable within maxnumber")  # pragma: no cover


def _parse_expires(salt: str) -> int | None:
    """Read the ``expires`` value from the salt query.

    Returns:
        The expiry in unix seconds. ``None`` when the salt holds no valid value.
    """
    query = urlparse(f"//x?{salt.split('?', 1)[1]}").query if "?" in salt else ""
    if not query:
        return None
    raw = parse_qs(query).get("expires", [None])[0]
    if raw is None or not raw.isdigit():
        return None
    return int(raw)


@dataclass(frozen=True)
class Solution:
    """A parsed proof-of-work solution.

    The structure is valid. No cryptographic check ran yet.
    """

    algorithm: str
    challenge: str
    number: int
    salt: str
    signature: str


def parse_solution(payload_b64: str) -> Solution:
    """Parse the structure of the solution payload.

    The function decodes base64, then JSON, then checks the required fields and their
    types. It needs no secret and does no cryptography. Full verification and early
    request validation both call it. A malformed input therefore always gets a 4xx
    answer, whatever the ALTCHA toggle says.

    Raises:
        AltchaError: The payload has an invalid structure.
    """
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
    # bool is a subclass of int. Exclude it here. A negative number is also invalid.
    if isinstance(number, bool) or not isinstance(number, int) or number < 0:
        raise AltchaError("malformed altcha payload")
    return Solution(
        algorithm=algorithm, challenge=challenge, number=number, salt=salt, signature=signature
    )


def validate_solution_format(value: str) -> str:
    """Pydantic ``AfterValidator`` that rejects a malformed ALTCHA payload with a 422.

    The validator runs in the request schema before any endpoint logic. It runs whether
    or not ALTCHA verification is active. A malformed payload therefore always gets the
    same problem+json 422. This keeps the enumeration protection intact, because the
    rejection depends only on the form of the payload. The function remaps
    ``AltchaError`` to ``ValueError``, because Pydantic turns only ``ValueError`` and
    ``AssertionError`` into a 422. Any other exception becomes a 500.

    Raises:
        ValueError: The payload has an invalid structure.
    """
    try:
        parse_solution(value)
    except AltchaError as exc:
        raise ValueError(f"malformed altcha solution: {exc}") from exc
    return value


AltchaSolutionStr = Annotated[str, AfterValidator(validate_solution_format)]
"""Request field type for an ALTCHA solution that enforces the payload form (422)."""


def verify_solution(payload_b64: str, secret: str, *, now: int) -> str:
    """Verify the algorithm, the hash, the HMAC and the expiry of a solution.

    The function compares the hash and the HMAC in constant time.

    Returns:
        The replay key of the solution.

    Raises:
        AltchaError: The solution is invalid or expired.
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
    """One-time-use store for solution keys.

    ``seen`` returns ``True`` when the key already appeared inside the window.
    """

    async def seen(self, key: str, ttl_seconds: int) -> bool: ...


class InMemoryReplayGuard:
    """Process-local replay protection for tests and single-worker development."""

    def __init__(self, *, now: Callable[[], int] | None = None) -> None:
        self._seen: dict[str, int] = {}
        self._now = now or _wall_clock

    async def seen(self, key: str, ttl_seconds: int) -> bool:
        now = self._now()
        # Drop the expired entries so the store does not grow without a bound.
        self._seen = {k: exp for k, exp in self._seen.items() if exp > now}
        if key in self._seen:
            return True
        self._seen[key] = now + ttl_seconds
        return False


class RedisReplayGuard:
    """Redis-backed replay protection with SET NX and a TTL, shared across workers.

    A Redis failure must NOT turn this guard into a no-op. A solved proof of work would
    then be replayable inside the TTL window. The guard falls back to a process-local
    ``InMemoryReplayGuard`` instead, so one-time use still holds per worker. That is
    defense in depth. Rate limiting may fail open. Replay protection must not.
    """

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
        # SET key 1 NX EX ttl returns None when the key exists, which means a replay.
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
    """Verify a solution and protect against a replay.

    The caller can inject ``now`` to test the expiry.
    """

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
        """Verify one solution.

        Raises:
            AltchaError: The solution is missing, invalid, expired, or already used.
        """
        if not payload_b64:
            raise AltchaError("altcha solution required")
        key = verify_solution(payload_b64, self._secret, now=self._now())
        if await self._replay.seen(key, self._replay_ttl):
            raise AltchaError("altcha solution already used")


class NullAltchaVerifier:
    """No-op verifier used when ALTCHA is off because no secret is configured."""

    async def verify(self, payload_b64: str | None) -> None:
        return None
