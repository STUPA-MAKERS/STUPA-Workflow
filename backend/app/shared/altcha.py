"""Serverseitige Altcha-Verifikation (Proof-of-Work, security.md §7, Issue #23).

Altcha-kompatibler HMAC-Mechanismus (altcha-lib / Sentinel): der Server signiert eine
PoW-Challenge mit `ALTCHA_HMAC_SECRET`; das FE löst die Challenge (sucht `number` mit
`SHA-256(salt+number) == challenge`) und schickt die Base64-kodierte Lösung zurück. Die
Verifikation ist rein lokal (HMAC + Hash-Recompute + Ablauf + Einmal-Nutzung) — kein
Drittanbieter, kein Tracking (DSGVO, security.md §7).

`create_challenge`/`solve_challenge` sind symmetrisch (Letzteres dient Tests/Dev als
Referenz-Solver). `verify_solution` ist eine reine Funktion ohne I/O; die Einmal-Nutzung
(Replay-Schutz) liegt im `ReplayGuard` und wird vom `AltchaVerifier` orchestriert.
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
    """Ungültige/fehlende/abgelaufene/wiederverwendete Altcha-Lösung."""


@dataclass(frozen=True)
class Challenge:
    """Vom Server signierte PoW-Challenge (an das FE ausgeliefert)."""

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
    """Signierte Challenge bauen. `expires` (Unix-Sekunden) wird in den Salt kodiert."""
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
    """Lösungs-Payload (Base64-JSON) bauen — Format wie altcha-lib es vom FE schickt."""
    payload = {
        "algorithm": challenge.algorithm,
        "challenge": challenge.challenge,
        "number": number,
        "salt": challenge.salt,
        "signature": challenge.signature,
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def solve_challenge(challenge: Challenge) -> str:
    """Referenz-Solver (Tests/Dev): brute-forced `number`, liefert Base64-Lösung."""
    for number in range(challenge.maxnumber + 1):
        if _sha256_hex(f"{challenge.salt}{number}") == challenge.challenge:
            return encode_solution(challenge, number)
    raise ValueError("challenge unsolvable within maxnumber")  # pragma: no cover


def _parse_expires(salt: str) -> int | None:
    """`expires`-Sekunden aus dem Salt-Query lesen (oder `None`, wenn keiner/ungültig)."""
    query = urlparse(f"//x?{salt.split('?', 1)[1]}").query if "?" in salt else ""
    if not query:
        return None
    raw = parse_qs(query).get("expires", [None])[0]
    if raw is None or not raw.isdigit():
        return None
    return int(raw)


@dataclass(frozen=True)
class Solution:
    """Strukturell geparste (noch **nicht** kryptografisch verifizierte) PoW-Lösung."""

    algorithm: str
    challenge: str
    number: int
    salt: str
    signature: str


def parse_solution(payload_b64: str) -> Solution:
    """Lösungs-Payload **strukturell** parsen (Base64→JSON→Pflichtfelder/Typen).

    Reine Form-Validierung ohne Secret/Krypto: prüft, dass `payload_b64` dekodierbares
    Base64-JSON mit den erwarteten Feldern und Typen ist. Wirft `AltchaError` bei jeder
    strukturellen Ungültigkeit (kaputtes Base64, kein JSON-Objekt, fehlende/falsch
    getypte Felder). Dient sowohl der vollen Verifikation (`verify_solution`) als auch
    der frühen Request-Validierung (`MagicLinkRequest`/`ApplicationCreate`), damit
    malformte Eingaben **unabhängig** vom Altcha-Schalter mit 4xx abgelehnt werden
    (Contract `negative_data_rejection`, Issue #23)."""
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
    # bool ist int-Subklasse → explizit ausschließen; negative Zahlen unzulässig.
    if isinstance(number, bool) or not isinstance(number, int) or number < 0:
        raise AltchaError("malformed altcha payload")
    return Solution(
        algorithm=algorithm, challenge=challenge, number=number, salt=salt, signature=signature
    )


def validate_solution_format(value: str) -> str:
    """Pydantic-`AfterValidator`: strukturell ungültiges Altcha → `ValueError` (→ 422).

    Greift im Request-Schema **vor** jeder Endpoint-Logik (Mail-Existenzprüfung,
    DB-Zugriff) und **unabhängig** davon, ob die Altcha-Verifikation aktiv ist. So wird
    ein malformtes Payload (Steuerzeichen, kein Base64-JSON, fehlende Felder) konsistent
    mit problem+json-422 abgelehnt, ohne den Enumeration-Schutz (konstante Antwort für
    existierende/nicht-existierende Mail) zu berühren — die Ablehnung hängt allein an der
    Payload-Form. `AltchaError` wird zu `ValueError` umgehängt, weil Pydantic nur
    `ValueError`/`AssertionError` zu Validierungsfehlern (422) macht (sonst 500)."""
    try:
        parse_solution(value)
    except AltchaError as exc:
        raise ValueError(f"malformed altcha solution: {exc}") from exc
    return value


AltchaSolutionStr = Annotated[str, AfterValidator(validate_solution_format)]
"""Request-Feldtyp für ein Altcha-Solution-Feld: erzwingt strukturelle Form (422)."""


def verify_solution(payload_b64: str, secret: str, *, now: int) -> str:
    """Lösung prüfen (Algorithmus, Hash, HMAC, Ablauf). Liefert den Replay-Schlüssel.

    Wirft `AltchaError` bei jeder Ungültigkeit. Konstante-Zeit-Vergleich für Hash/HMAC.
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
    """Einmal-Nutzung: `True`, wenn der Schlüssel im Fenster bereits gesehen wurde."""

    async def seen(self, key: str, ttl_seconds: int) -> bool: ...


class InMemoryReplayGuard:
    """Prozesslokaler Replay-Schutz (Tests/Single-Worker-Dev)."""

    def __init__(self, *, now: Callable[[], int] | None = None) -> None:
        self._seen: dict[str, int] = {}
        self._now = now or _wall_clock

    async def seen(self, key: str, ttl_seconds: int) -> bool:
        now = self._now()
        # Abgelaufene Einträge ernten, damit der Speicher nicht unbegrenzt wächst.
        self._seen = {k: exp for k, exp in self._seen.items() if exp > now}
        if key in self._seen:
            return True
        self._seen[key] = now + ttl_seconds
        return False


class RedisReplayGuard:
    """Replay-Schutz über Redis (SET NX + TTL) — geteilt über alle Worker.

    Fällt bei Redis-Ausfall **nicht** auf no-op zurück (sonst wäre eine gelöste PoW im
    TTL-Fenster unbegrenzt replaybar), sondern auf einen prozesslokalen
    `InMemoryReplayGuard`: dann gilt Einmal-Nutzung wenigstens **pro Worker** statt gar
    nicht (defense-in-depth, security.md §7). Rate-Limit darf fail-open bleiben,
    Replay-Schutz nicht."""

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
        # SET key 1 NX EX ttl → None, wenn bereits vorhanden (= Replay).
        try:
            stored = await self._client.set(  # type: ignore[attr-defined]
                f"{self._prefix}{key}", "1", nx=True, ex=ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001 — Redis weg → prozesslokaler Fallback
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
    """Verifikation + Replay-Schutz; `now` injizierbar (Tests/Ablauf)."""

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
        """Raises `AltchaError`, wenn Lösung fehlt/ungültig/abgelaufen/wiederverwendet."""
        if not payload_b64:
            raise AltchaError("altcha solution required")
        key = verify_solution(payload_b64, self._secret, now=self._now())
        if await self._replay.seen(key, self._replay_ttl):
            raise AltchaError("altcha solution already used")


class NullAltchaVerifier:
    """No-op-Verifier (Altcha aus: kein Secret konfiguriert, Dev/Test)."""

    async def verify(self, payload_b64: str | None) -> None:
        return None
