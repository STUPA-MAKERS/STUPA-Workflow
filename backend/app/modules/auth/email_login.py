"""E-mail login for applicants.

A person requests a login link for an address. The link opens an applicant session
that is bound to the address, not to one application. At each request the session
reaches every application whose applicant e-mail is the address (case-insensitive,
the column is CITEXT).

The rules:

- Every address gets a link, also the address of a platform account. The session is
  an applicant session only: it carries no principal, so it gets no role, permission,
  Gremium or page of the account. The account login stays the SSO.
- A link works once. A link from the login page ends 30 minutes after the request. A
  link in the mail after a new application ends with the confirmation window of that
  application. A request ends no other link, because anybody who knows the address
  can request one.
- The first redeem confirms every guest application of the address that waits for the
  confirmation and starts its flow, because the link proves that the person reads the
  mailbox. A confirmed guest application of an address that an active account holds
  then belongs to that account (`assign_to_accounts`), never before the confirmation.
- A session reads the application list fresh at each request (`resolve_session`), so
  an anonymized application drops out and a new one joins.

The caller answers 202 for every request and runs `request_email_login` in the
background, so the answer tells nothing about the address. Service functions do not
commit; the caller owns the transaction.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Applicant as ApplicantRow
from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth import sessions, tokens
from app.modules.auth.models import EmailLoginLink
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Applicant
from app.modules.flow.dispatch import ActionDispatcher
from app.modules.flow.service import FlowService
from app.settings import Settings
from app.shared.errors import GoneError

#: Lifetime of a login link from the login page, counted from the request.
LINK_TTL = timedelta(minutes=30)
#: The page that the link opens. The token rides the fragment, never the query.
LINK_PATH = "/my-applications"
#: The audit actor of the account assignment after a confirmation.
OWNER_MATCH_ACTOR = "system:email-login"

#: Delivery callback of the link mail `(email, link)`, sync or async.
SendLink = Callable[[str, str], None | Awaitable[None]]


def _now() -> datetime:
    return datetime.now(UTC)


async def _call(result: None | Awaitable[None]) -> None:
    """Await the result of a delivery callback when it is awaitable."""
    if inspect.isawaitable(result):
        await result


async def application_ids(db: AsyncSession, email: str) -> frozenset[str]:
    """Return the ids of every application whose applicant e-mail is the address."""
    rows = await db.scalars(
        select(ApplicantRow.application_id).where(ApplicantRow.email == email)
    )
    return frozenset(str(app_id) for app_id in rows)


async def issue_link(
    db: AsyncSession, settings: Settings, *, email: str, expires_at: datetime
) -> str:
    """Store a new login link for an address and return its URL.

    Only the peppered hash of the token is stored. The token rides the fragment.
    """
    token = tokens.generate_token()
    db.add(
        EmailLoginLink(
            email=email,
            token_hash=tokens.hash_token(token, settings.magic_link_secret),
            expires_at=expires_at,
        )
    )
    await db.flush()
    return f"{settings.public_base_url.rstrip('/')}{LINK_PATH}#t={token}"


async def request_email_login(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str,
    send_link: SendLink,
) -> None:
    """Make and send a login link, or nothing.

    An address gets a link only when at least one application has the address. The
    state of an account with the address does not matter.
    """
    if not await application_ids(db, email):
        return
    link = await issue_link(db, settings, email=email, expires_at=_now() + LINK_TTL)
    await _call(send_link(email, link))


async def issue_confirm_link(db: AsyncSession, settings: Settings, *, email: str) -> str:
    """Store the login link of the mail after a new Antrag and return its URL.

    The link ends with the confirmation window of the Antrag (`confirm_ttl_hours`),
    because it is the link that confirms the Antrag.
    """
    from app.modules.applications.guest_settings import load_guest_settings

    hours = (await load_guest_settings(db)).confirm_ttl_hours
    return await issue_link(db, settings, email=email, expires_at=_now() + timedelta(hours=hours))


async def assign_to_accounts(db: AsyncSession, app_ids: Iterable[object]) -> None:
    """Give each just confirmed guest application to the active account of its e-mail.

    An application that already has an owner stays as it is. Of several active
    accounts with the address, the one with the newest login wins, as in the capture
    (`F/applications/applications/000124`). Each assignment writes one audit entry
    with ``matchedByEmail``.
    """
    ids = list(app_ids)
    if not ids:
        return
    rows = (
        await db.execute(
            select(Application.id, PrincipalRow.id, PrincipalRow.sub)
            .join(ApplicantRow, ApplicantRow.application_id == Application.id)
            .join(PrincipalRow, PrincipalRow.email == ApplicantRow.email)
            .where(
                Application.id.in_(ids),
                Application.created_by.is_(None),
                PrincipalRow.active.is_(True),
                PrincipalRow.merged_into.is_(None),
            )
            .order_by(Application.id, PrincipalRow.last_login.desc().nulls_last())
        )
    ).all()
    owners: dict[object, tuple[object, str]] = {}
    for app_id, principal_id, sub in rows:
        owners.setdefault(app_id, (principal_id, sub))
    for app_id, (principal_id, sub) in owners.items():
        await db.execute(
            update(Application)
            .where(Application.id == app_id, Application.created_by.is_(None))
            .values(created_by=sub)
        )
        await audit_record(
            db,
            actor=OWNER_MATCH_ACTOR,
            action=AuditAction.APPLICATION_OWNER_MATCH,
            target_type="application",
            target_id=str(app_id),
            data={"principalId": str(principal_id), "matchedByEmail": True},
        )


async def verify_email_login(
    db: AsyncSession,
    settings: Settings,
    *,
    token: str,
    dispatcher: ActionDispatcher | None = None,
) -> str:
    """Redeem a login link and open an applicant session for its address.

    The redeem marks the link used in one conditional UPDATE, so of two concurrent
    redeems only one gets the row. The redeem confirms every waiting guest application
    of the address, gives it to the account of the address if there is one, and starts
    its flow.

    Returns:
        The signed applicant session token.

    Raises:
        GoneError: The token is unknown, used or expired.
    """
    digest = tokens.hash_token(token, settings.magic_link_secret)
    row = (
        await db.execute(select(EmailLoginLink).where(EmailLoginLink.token_hash == digest))
    ).scalar_one_or_none()
    if row is None or not tokens.verify_token_hash(
        token, settings.magic_link_secret, row.token_hash
    ):
        raise GoneError("Login link invalid or expired.")
    now = _now()
    email = (
        await db.execute(
            update(EmailLoginLink)
            .where(
                EmailLoginLink.id == row.id,
                EmailLoginLink.used_at.is_(None),
                EmailLoginLink.expires_at > now,
            )
            .values(used_at=now)
            .returning(EmailLoginLink.email)
        )
    ).scalar_one_or_none()
    if email is None:
        raise GoneError("Login link invalid or expired.")
    confirmed = list(
        await db.scalars(
            update(Application)
            .where(
                Application.id.in_(
                    select(ApplicantRow.application_id).where(ApplicantRow.email == email)
                ),
                Application.email_confirmed_at.is_(None),
            )
            .values(email_confirmed_at=now)
            .returning(Application.id)
        )
    )
    await assign_to_accounts(db, confirmed)
    session_token = await sessions.create_applicant_session(
        db,
        secret=settings.session_secret,
        email=email,
        expires_at=now + timedelta(hours=settings.applicant_session_ttl_hours),
    )
    for app_id in confirmed:
        await FlowService(db, dispatcher).start_confirmed(app_id)
    return session_token


async def resolve_session(db: AsyncSession, email: str) -> Applicant:
    """Turn an e-mail session into an `Applicant` with the applications of now."""
    return Applicant(email=email, application_ids=await application_ids(db, email))
