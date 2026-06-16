"""Reine OAuth2-Helfer (DB-frei): Scope-Katalog, PKCE-Prüfung, Token-Erzeugung/-Hash.

Scopes kappen die Rechte des eingeloggten Principals: ein scoped Token erhält genau die
Schnittmenge aus den RBAC-Permissions des Nutzers und der dem Scope zugeordneten
Permission-Menge (siehe ``Principal.scope_permissions``). Das gilt **auch** für Admins —
der Admin-Bypass in ``Principal.has`` greift nur, wenn die Permission im Scope liegt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Permissions, die einem Agenten NIE gewährt werden dürfen — unabhängig von Scope
# oder Admin-Status. `vote.cast` (eine Stimme abgeben) ist strikt menschlich (#MCP):
# wird aus jeder Scope-Auflösung hart entfernt.
FORBIDDEN_PERMISSIONS: frozenset[str] = frozenset({"vote.cast"})

# Scope-Key → erlaubte Permission-Keys (Teilmenge des PERMISSION_CATALOGUE).
# `read` deckt alle lesenden Endpunkte; die `*:write`-Scopes ergänzen Mutationen.
# Hinweis: `votes:write` umfasst NUR die Vote-VERWALTUNG (anlegen/öffnen/schließen),
# nicht `vote.cast` — das Abstimmen selbst bleibt Menschen vorbehalten.
SCOPES: dict[str, frozenset[str]] = {
    "read": frozenset(
        {
            "application.read",
            "application.export",
            "budget.view",
            "budget.export",
            "audit.read",
            "audit.verify",
        }
    ),
    "applications:write": frozenset(
        {"application.create", "application.transition", "application.manage"}
    ),
    "votes:write": frozenset({"vote.manage"}),
    "budget:write": frozenset({"budget.structure", "budget.book", "account.manage"}),
    "meetings:write": frozenset({"meeting.manage", "protocol.finalize"}),
    "forms:write": frozenset({"form.configure"}),
    "flows:write": frozenset({"flow.configure"}),
    "admin:write": frozenset(
        {
            "admin.site",
            "admin.gremien",
            "admin.types",
            "admin.roles",
            "admin.users",
            "admin.group_mappings",
            "admin.gremium_roles",
            "admin.delegations",
            "admin.deadlines",
            "webhook.manage",
        }
    ),
}

# Voller kuratierter Umfang (MCP-Default-Request). Serverseitig auf die Rechte des
# eingeloggten Nutzers gekappt — ein Nicht-Admin erhält nur seine Teilmenge.
DEFAULT_SCOPE = " ".join(SCOPES.keys())

# Harte Obergrenze für jede Token-Lebensdauer (Sekunden). Es gibt KEINE nie ablaufenden
# Tokens mehr (security): selbst der längste wählbare Wert ist hierdurch gedeckelt.
MAX_LIFETIME_SECONDS = 90 * 24 * 3600  # 90 Tage

# Wählbare Token-Lebensdauern (Consent-UI) → Access-Token-TTL in Sekunden. Reihenfolge =
# Anzeige. Eine "never"-Option gibt es bewusst nicht — jedes Token läuft ab (≤ 90d),
# unabhängig vom jederzeit möglichen Widerruf über die Grants-Seite.
LIFETIMES: dict[str, int] = {
    "1h": 3600,
    "8h": 8 * 3600,
    "1d": 24 * 3600,
    "30d": 30 * 24 * 3600,
    "90d": 90 * 24 * 3600,
}
DEFAULT_LIFETIME = "30d"


def resolve_lifetime(key: str | None) -> int:
    """Lifetime-Key → Access-TTL (Sekunden). Unbekannt/``None`` → Default.

    Das Ergebnis ist immer endlich und durch ``MAX_LIFETIME_SECONDS`` gedeckelt — es
    kann nie ``None`` (unbegrenzt) zurückgeben."""
    if key is None or key not in LIFETIMES:
        key = DEFAULT_LIFETIME
    return min(LIFETIMES[key], MAX_LIFETIME_SECONDS)


# i18n-Schlüssel-Stamm je Scope für die Consent-UI (Label/Beschreibung im FE).
SCOPE_ORDER: tuple[str, ...] = (
    "read",
    "applications:write",
    "votes:write",
    "meetings:write",
    "budget:write",
    "forms:write",
    "flows:write",
    "admin:write",
)

_ACCESS_PREFIX = "apat_"  # antragsplattform access token
_REFRESH_PREFIX = "aprt_"  # antragsplattform refresh token
_TOKEN_BYTES = 32


class OAuthError(ValueError):
    """OAuth2-Protokollfehler (→ 400 invalid_request/invalid_grant am Endpoint)."""

    def __init__(self, error: str, description: str = "") -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description


def parse_scope(raw: str | None) -> list[str]:
    """Space-separierten Scope-String → validierte, deduplizierte Liste.

    Unbekannte Scopes → ``OAuthError('invalid_scope')``. Leer → ``[DEFAULT_SCOPE]``.
    """
    if not raw or not raw.strip():
        raw = DEFAULT_SCOPE
    out: list[str] = []
    for tok in raw.split():
        if tok not in SCOPES:
            raise OAuthError("invalid_scope", f"unknown scope: {tok}")
        if tok not in out:
            out.append(tok)
    return out


def scope_permissions(scopes: list[str]) -> frozenset[str]:
    """Vereinigung der Permission-Mengen aller Scopes, minus FORBIDDEN_PERMISSIONS.

    `vote.cast` & Co. werden hier hart entfernt — selbst wenn ein Scope sie je
    enthielte oder der Nutzer Admin ist (der Admin-Bypass wird durch die Scope-Kappung
    in ``Principal.has`` neutralisiert)."""
    perms: set[str] = set()
    for s in scopes:
        perms |= SCOPES.get(s, frozenset())
    return frozenset(perms - FORBIDDEN_PERMISSIONS)


def is_access_token(token: str) -> bool:
    return token.startswith(_ACCESS_PREFIX)


def generate_access_token() -> str:
    return _ACCESS_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def generate_refresh_token() -> str:
    return _REFRESH_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """SHA-256-Digest eines Tokens (für DB-Speicherung; Klartext nie persistiert)."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def tokens_match(token: str, expected_hash: bytes) -> bool:
    """Konstant-zeitiger Vergleich Token↔gespeicherter Hash."""
    return hmac.compare_digest(hash_token(token), expected_hash)


def verify_pkce_s256(verifier: str, challenge: str) -> bool:
    """RFC 7636 S256: ``base64url(sha256(verifier)) == challenge`` (konstant-zeitig)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(expected, challenge)
