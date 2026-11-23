"""The signed token of a push button that acts in the background.

A direct action of a push (§F/collaboration/notifications/002509) runs without a session:
the service worker fetches the URL of the button. The URL carries a token that names the
person, the action and the element, signed with the session secret under its own salt.
It is valid for seven days and allows nothing else, so a leaked token can at most repeat
that one answer of that one person.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

#: The actions that a push button can run in the background.
PushActionKind = Literal["appointment_accept", "appointment_decline", "todo_done"]

#: The lifetime of a token: seven days, because a push can wait on a lock screen.
TOKEN_MAX_AGE_SECONDS = 7 * 24 * 3600

_SALT = "push-action"


@dataclass(frozen=True, slots=True)
class PushActionClaim:
    """What a valid token allows: one action of one person on one element."""

    principal_id: uuid.UUID
    action: PushActionKind
    target_id: uuid.UUID


class PushTokenError(Exception):
    """The token is forged, expired or names an unknown action."""


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_SALT)


def sign_action(secret: str, claim: PushActionClaim) -> str:
    """Return the token of ``claim``."""
    return str(
        _serializer(secret).dumps(
            {"p": str(claim.principal_id), "a": claim.action, "t": str(claim.target_id)}
        )
    )


def _action(value: object) -> PushActionKind:
    match value:
        case "appointment_accept":
            return "appointment_accept"
        case "appointment_decline":
            return "appointment_decline"
        case "todo_done":
            return "todo_done"
        case _:
            raise PushTokenError("unknown push action")


def read_action(
    secret: str, token: str, *, max_age: int = TOKEN_MAX_AGE_SECONDS
) -> PushActionClaim:
    """Check ``token`` and return its claim.

    Raises:
        PushTokenError: The signature is wrong, the token is older than ``max_age``
            seconds, or its content is not a claim.
    """
    try:
        data = _serializer(secret).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired) as exc:
        raise PushTokenError("invalid push token") from exc
    if not isinstance(data, dict):
        raise PushTokenError("invalid push token")
    try:
        return PushActionClaim(
            principal_id=uuid.UUID(str(data["p"])),
            action=_action(data["a"]),
            target_id=uuid.UUID(str(data["t"])),
        )
    except (KeyError, ValueError) as exc:
        raise PushTokenError("invalid push token") from exc

