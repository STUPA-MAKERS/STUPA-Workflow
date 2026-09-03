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
import uuid as _uuid
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, ApplicationShare
from app.modules.auth import tokens

# The SAME offer parser and total the form validator uses. A second implementation here
# would let the page and the validated total disagree about what an application costs,
# and the page is the copy an outsider reads.
from app.modules.forms.validation import _offer_value, positions_total
from app.shared.config_schemas import FieldOption, FormFieldDef
from app.shared.errors import NotFoundError
from app.shared.i18n import resolve_i18n

#: Reader-facing date format. `%d.%m.%Y`, the one the protocol and the notification mails
#: already use, rather than a second convention for one page.
_DATE_FORMAT = "%d.%m.%Y"

#: The currency an application carries no explicit one for.
_DEFAULT_CURRENCY = "EUR"

#: Bytes of entropy in a share token. The URL is the only secret, so it carries the same
#: weight as a session token rather than a coupon code.
TOKEN_BYTES = 32

#: How long a new link lives unless the caller says otherwise. Long enough to be useful
#: in a chat thread, short enough that a forgotten link stops working by itself.
DEFAULT_TTL_DAYS = 30

#: Upper bound. "Never expires" is not on offer: the whole point of an expiry is that a
#: link nobody remembers eventually stops being a way in.
MAX_TTL_DAYS = 365


@dataclass(slots=True, frozen=True)
class Offer:
    """One comparison quote. `value` is already formatted; the page only escapes it."""

    label: str
    value: str
    preferred: bool


@dataclass(slots=True, frozen=True)
class Position:
    """One cost position, worth its preferred offer.

    `no_offers_reason` is set only where the applicant opted out of the comparison. The
    opt-out without its reason would read as a missing comparison rather than an
    explained one, so the two travel together or not at all.
    """

    label: str
    value: str | None
    offers: list[Offer]
    no_offers_reason: str | None


@dataclass(slots=True, frozen=True)
class PositionBlock:
    """One `positions` field: its label, its positions and their total."""

    label: str
    positions: list[Position]
    total: str | None


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
    #: Cost breakdowns, rendered as blocks rather than squeezed into a single line. They
    #: follow the scalar rows, the same order the internal detail view uses.
    positions: list[PositionBlock] = dc_field(default_factory=list)


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
    currency = app.currency or _DEFAULT_CURRENCY
    shown: list[tuple[str, str]] = []
    blocks: list[PositionBlock] = []
    for f in fields:
        if f.is_pii:
            continue
        value = data.get(f.key)
        if value in (None, "", [], {}):
            continue
        label = resolve_i18n(f.label, lang, "de") or f.key
        # A cost breakdown is the substance of a funding application. Flattened to one
        # line it says nothing, so it becomes a block instead of a row.
        if f.type == "positions":
            block = _positions_block(value, label=label, lang=lang, currency=currency)
            if block is not None:
                blocks.append(block)
            continue
        text = _format_field(f, value, lang=lang, currency=currency)
        # A field that flattens to nothing is left out rather than printed empty. A list
        # of structured rows would otherwise render as ", , ," — punctuation around
        # values this page deliberately does not show.
        if not text.strip(" ,"):
            continue
        shown.append((label, text))
    return PublicApplication(
        title=str(data.get("title") or "").strip() or str(app.id),
        type_name=type_name,
        gremium_name=gremium_name,
        state_label=state_label,
        amount=str(app.amount) if app.amount is not None else None,
        currency=app.currency,
        created_at=app.created_at,
        fields=shown,
        positions=blocks,
    )


def _positions_block(
    value: object, *, label: str, lang: str, currency: str
) -> PositionBlock | None:
    """Build one cost breakdown, or `None` where there is nothing readable to show.

    The answer is JSONB written by whatever form version was active at the time, so every
    level checks its own shape. A public route may not raise on an old answer: that turns
    a valid link into a 500.
    """
    if not isinstance(value, list):
        return None
    positions: list[Position] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        offers: list[Offer] = []
        preferred: Decimal | None = None
        raw_offers = raw.get("offers")
        if isinstance(raw_offers, list):
            for raw_offer in raw_offers:
                if not isinstance(raw_offer, dict):
                    continue
                num = _offer_value(raw_offer)
                if num is None:
                    continue
                is_preferred = raw_offer.get("preferred") is True
                offers.append(
                    Offer(
                        label=str(raw_offer.get("label") or "").strip(),
                        value=format_money(num, currency, lang),
                        preferred=is_preferred,
                    )
                )
                if is_preferred and preferred is None:
                    preferred = num
        pos_label = str(raw.get("label") or "").strip()
        # A position with neither a name nor a single readable offer carries nothing.
        if not pos_label and not offers:
            continue
        reason = raw.get("noOffersReason") if raw.get("noOffers") is True else None
        positions.append(
            Position(
                label=pos_label,
                value=format_money(preferred, currency, lang) if preferred is not None else None,
                offers=offers,
                no_offers_reason=(
                    reason.strip() if isinstance(reason, str) and reason.strip() else None
                ),
            )
        )
    if not positions:
        return None
    total = positions_total(value)
    return PositionBlock(
        label=label,
        positions=positions,
        total=format_money(total, currency, lang) if total is not None else None,
    )


def _format_field(f: FormFieldDef, value: object, *, lang: str, currency: str) -> str:
    """Flatten one answer to a display string, using what the field type promises.

    Type-aware rather than value-aware on purpose: the shape of an answer alone cannot
    say whether a dict is a date range or an internal record, and guessing risks printing
    a key nobody meant to publish.
    """
    if f.type in ("select", "gremium_select", "budget_select"):
        return _option_label(f.options, value, lang)
    if f.type == "multiselect" and isinstance(value, list):
        parts = [_option_label(f.options, v, lang) for v in value]
        return ", ".join(p for p in parts if p)
    if f.type == "currency":
        num = to_decimal(value)
        return format_money(num, currency, lang) if num is not None else _format(value)
    if f.type == "daterange" and isinstance(value, dict):
        return _daterange(value)
    if f.type == "date":
        return _day(value)
    return _format(value)


def _option_label(options: list[FieldOption] | None, value: object, lang: str) -> str:
    """Resolve a stored option value to its label.

    The stored value is a machine key, and for a Gremium or budget picker it is a UUID
    whose options the server injects at render time and which this page does not have.
    Without a matching option the plain rule applies, so an id is dropped rather than
    published.
    """
    for option in options or ():
        if option.value == value:
            return resolve_i18n(option.label, lang, "de") or option.value
    return _format(value)


def _daterange(value: dict[str, Any]) -> str:
    """`{"from": ISO, "to": ISO}` as one span. A half-filled range shows the half it has.

    Each end is checked before it is formatted. A missing key would otherwise be printed
    as the word "None", which reads like an answer.
    """
    ends = [value.get(k) for k in ("from", "to")]
    both = [_day(end) for end in ends if isinstance(end, str) and end.strip()]
    if len(both) == 2:
        return f"{both[0]} – {both[1]}"
    return both[0] if both else ""


def _day(value: object) -> str:
    """One ISO date in the house format, or the stored text where it is not one.

    An answer an older form version never validated is still what the applicant wrote.
    Dropping it loses information the reader is entitled to.
    """
    if not isinstance(value, str):
        return _format(value)
    try:
        return date.fromisoformat(value).strftime(_DATE_FORMAT)
    except ValueError:
        return value


def to_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return num if num.is_finite() else None


def format_money(value: Decimal, currency: str, lang: str) -> str:
    """Format an amount for a reader.

    Written out rather than taken from a locale library: the backend has no locale data
    dependency, and the page only ever needs the two languages the platform speaks.
    """
    amount = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    whole, _, cents = f"{abs(amount):.2f}".partition(".")
    symbol = "€" if currency == "EUR" else currency
    if lang == "en":
        grouped = _group(whole, ",")
        joiner = "" if symbol == "€" else " "
        return f"{sign}{symbol}{joiner}{grouped}.{cents}"
    return f"{sign}{_group(whole, '.')},{cents} {symbol}"


def _group(digits: str, sep: str) -> str:
    """Thousands separators, right to left."""
    out = ""
    for i, ch in enumerate(reversed(digits)):
        if i and i % 3 == 0:
            out = sep + out
        out = ch + out
    return out


def _format(value: object) -> str:
    """Flatten one answer to a display string. No HTML, no markup — the template escapes."""
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, list):
        parts = [p for p in (_format(v) for v in value) if p]
        return ", ".join(parts)
    if isinstance(value, dict):
        # A structured answer has no sensible one-line form, and guessing one risks
        # printing a key nobody meant to publish.
        return ""
    text = str(value)
    # A reference field holds the id of the thing it points at. On a public page that id
    # names nothing the reader can use and publishes an internal identifier, so the
    # value is dropped rather than shown raw.
    if _is_uuid(text):
        return ""
    return text


def _is_uuid(text: str) -> bool:
    try:
        _uuid.UUID(text)
    except ValueError:
        return False
    return True
