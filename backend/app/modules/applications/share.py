"""Public, read-only share links to one application.

Two halves that must not be confused:

* **Creating a link** is an authenticated action, gated on ``application.share``. Reading
  an application and deciding it may be read by anyone holding a URL are different
  decisions, which is why the permission is its own and why someone reading through a
  magic link cannot publish.
* **Opening a link** is unauthenticated. It resolves a token to exactly one application
  and renders a fixed, reduced view. It deliberately does NOT go through
  ``resolve_access``: that function answers "may this principal read this?", and here
  there is no principal. Reusing it would mean inventing one, which is how a public route
  ends up with more access than intended.

The database stores ``HMAC-SHA256(pepper, token)`` and never the plaintext, like
``magic_link``. A stolen database yields no working links.

What the public view omits, and why:

* **Comments** and **version history** — the user asked for both to stay out. They are the
  committee's working record, not the decision.
* **Fields marked ``is_pii``** — the same rule ``be-pdf`` already applies to the gremium
  PDF. Reusing it rather than writing a second one means the two can never drift into
  disagreeing about what counts as personal.
* **The applicant record** entirely. A name is the most obviously personal thing on an
  application and the least necessary to understand it.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, ApplicationShare
from app.modules.auth import tokens
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError
from app.shared.i18n import resolve_i18n

#: Bytes of entropy in a share token. The URL is the only secret, so it carries the same
#: weight as a session token rather than a coupon code.
TOKEN_BYTES = 32

#: How long a new link lives unless the caller says otherwise. Long enough to be useful
#: in a chat thread, short enough that a forgotten link stops working by itself.
DEFAULT_TTL_DAYS = 30

#: Upper bound. "Never expires" is not on offer: the whole point of an expiry is that a
#: link nobody remembers eventually stops being a way in.
MAX_TTL_DAYS = 365


@dataclass(slots=True)
class PublicApplication:
    """Exactly what a public page may show. Nothing here is optional to review.

    A dataclass rather than the ORM row on purpose: whatever is not on this type cannot
    reach the template by accident, so adding a column to `Application` can never quietly
    publish it.
    """

    title: str
    type_name: str | None
    gremium_name: str | None
    state_label: str | None
    amount: str | None
    currency: str | None
    created_at: datetime
    #: Label/value pairs, already filtered and formatted. No keys, no raw JSON.
    fields: list[tuple[str, str]]


def new_token() -> str:
    """A fresh share token. The plaintext exists here and in the URL, nowhere else."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def clamp_ttl(days: int | None) -> int:
    """Bound the requested lifetime. `None` takes the default."""
    if days is None:
        return DEFAULT_TTL_DAYS
    return max(1, min(days, MAX_TTL_DAYS))


class ShareService:
    def __init__(self, session: AsyncSession, *, pepper: str) -> None:
        self.session = session
        self.pepper = pepper

    async def create(
        self,
        application_id: UUID,
        *,
        actor: str | None,
        ttl_days: int | None = None,
        label: str | None = None,
        now: datetime | None = None,
    ) -> tuple[ApplicationShare, str]:
        """Mint a link and return the row together with the PLAINTEXT token.

        The plaintext is returned once and never stored. A caller who loses it makes a new
        link; there is no way to recover the old one, which is the same promise the
        magic-link flow makes.
        """
        at = now or datetime.now(UTC)
        # Check the application first. Without this the INSERT trips the foreign key and
        # the caller gets a 500 where the route promises a 404 — and a 500 for a typo in
        # a URL reads as "the server broke" rather than "no such application".
        if await self.session.get(Application, application_id) is None:
            raise NotFoundError("no such application")
        token = new_token()
        row = ApplicationShare(
            application_id=application_id,
            token_hash=tokens.hash_token(token, self.pepper),
            expires_at=at + timedelta(days=clamp_ttl(ttl_days)),
            created_by=actor,
            label=label,
        )
        self.session.add(row)
        # Flush, do not just add. `id` and `created_at` are server defaults
        # (`gen_random_uuid()` and `now()`), so before the INSERT they are both None and
        # the response model has nothing to serialize.
        await self.session.flush()
        return row, token

    async def resolve(
        self, token: str, *, now: datetime | None = None
    ) -> ApplicationShare:
        """Find the live share for a token, or raise.

        Expired and revoked both answer 404 rather than 410. A public route must not
        confirm that a token was ever valid: "this link expired" tells a stranger they
        found a real one and are only too late.
        """
        at = now or datetime.now(UTC)
        digest = tokens.hash_token(token, self.pepper)
        row = await self.session.scalar(
            select(ApplicationShare).where(ApplicationShare.token_hash == digest)
        )
        if row is None or row.revoked_at is not None or row.expires_at <= at:
            raise NotFoundError("no such link")
        return row

    async def revoke(
        self, share_id: UUID, *, application_id: UUID, now: datetime | None = None
    ) -> ApplicationShare:
        """Stop honouring a link. Idempotent: revoking twice keeps the first timestamp."""
        row = await self.session.scalar(
            select(ApplicationShare).where(
                ApplicationShare.id == share_id,
                # Scoped to the application in the path, so a share id from one
                # application cannot be revoked through another's route.
                ApplicationShare.application_id == application_id,
            )
        )
        if row is None:
            raise NotFoundError("no such link")
        if row.revoked_at is None:
            row.revoked_at = now or datetime.now(UTC)
        return row

    async def list_for(self, application_id: UUID) -> list[ApplicationShare]:
        """Every link ever minted for this application, newest first.

        Revoked and expired ones stay in the list. "Revocable" is only meaningful if you
        can see what you revoked, and a link that once existed is part of the record of
        who published what.
        """
        rows = await self.session.scalars(
            select(ApplicationShare)
            .where(ApplicationShare.application_id == application_id)
            .order_by(ApplicationShare.created_at.desc())
        )
        return list(rows)


def build_public_view(
    app: Application,
    *,
    fields: list[FormFieldDef],
    type_name: str | None,
    gremium_name: str | None,
    state_label: str | None,
    lang: str,
) -> PublicApplication:
    """Reduce an application to what a public page may show.

    The field loop mirrors `be-pdf`'s: skip `is_pii`, resolve the label, format the value.
    Everything not explicitly copied here stays behind.
    """
    data: dict[str, Any] = app.data if isinstance(app.data, dict) else {}
    shown: list[tuple[str, str]] = []
    for f in fields:
        if f.is_pii:
            continue
        value = data.get(f.key)
        if value in (None, "", [], {}):
            continue
        label = resolve_i18n(f.label, lang, "de") or f.key
        shown.append((label, _format(value)))
    return PublicApplication(
        title=str(data.get("title") or "").strip() or str(app.id),
        type_name=type_name,
        gremium_name=gremium_name,
        state_label=state_label,
        amount=str(app.amount) if app.amount is not None else None,
        currency=app.currency,
        created_at=app.created_at,
        fields=shown,
    )


def _format(value: object) -> str:
    """Flatten one answer to a display string. No HTML, no markup — the template escapes."""
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, list):
        return ", ".join(_format(v) for v in value)
    if isinstance(value, dict):
        # A structured answer has no sensible one-line form, and guessing one risks
        # printing a key nobody meant to publish.
        return ""
    return str(value)
