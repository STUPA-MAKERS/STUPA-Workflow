"""Privacy/GDPR services: principal erasure, erasure-request queue, retention settings.

The router or the worker sends the notifications best-effort after the commit. This
module sends none.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.membership_sync import sync_principal_memberships
from app.modules.admin.models import ApplicationType
from app.modules.applications.models import (
    Applicant,
    Application,
    Comment,
    SubmissionVersion,
)
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import AuthSession, Principal
from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.flow.models import State
from app.modules.livevote.models import Meeting, MeetingAttendance
from app.modules.privacy.models import ErasureRequest, PrivacySettings
from app.modules.protocol.erasure import erase_candidate_names
from app.modules.tickets.models import Ticket
from app.modules.tickets.service import (
    TicketService,
    erase_sender_blocks,
    format_number,
    sender_blocks_of,
)
from app.modules.todos.privacy import erase_todos, todo_export
from app.modules.voting.erasure import erase_candidacies
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


def _now() -> datetime:
    return datetime.now(UTC)


def _i18n(value: dict[str, str] | None, locale: str) -> str:
    """Pick a localized value from an i18n map, with fallback to de then en."""
    data = value or {}
    return data.get(locale) or data.get("de") or data.get("en") or ""


class PrincipalService:
    """Principal erasure (GDPR Art. 17)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.storage_keys: list[str] = []

    async def erase(
        self,
        principal_id: UUID,
        *,
        actor: str,
        commit: bool = True,
        files: FilesService | None = None,
    ) -> Principal:
        """Null the PII fields, deactivate the principal, and drop the sessions.

        The `sub` stays as a pseudonym for the audit chain. The IdP deletes the user
        out of band. The pseudonymity that remains depends on that deletion.

        The tickets that the principal reported get the ticket anonymization: no
        reporter, no context, no attachments. This covers the reports of the account
        and the reports without a session under the e-mail of the account. With an
        object storage in `files` the attachment objects go too. Notes and events keep
        the principal id, so they show a deleted person; only the ``created`` event
        loses its actor.

        The to-do assignments of the principal go, and so does the personal board
        with the files of its comments. Cards, comments, their files and events on the
        shared boards keep the principal id and show "Gelöschte Person". The objects
        of those comment files go only after the commit, because a rollback brings the
        rows back and a row without its object is a broken download. With
        ``commit=False`` the keys collect in ``storage_keys``, and the caller removes
        them after its own commit.

        The sender blocks of the account and of its e-mail go too.

        Raises:
            NotFoundError: No principal has this id.
            ConflictError: The actor is the principal itself (`erase_self`), or the
                principal is merged into another account (`erase_merged`).
        """
        principal = await self.session.get(Principal, principal_id)
        if principal is None:
            raise NotFoundError(f"principal {principal_id} not found")
        # An admin who erases the own account locks out the session that does it and
        # can leave the platform without an admin. Another admin must do it.
        if principal.sub == actor:
            raise ConflictError(
                "You cannot erase your own account. Ask another administrator.",
                code="erase_self",
            )
        # A merged account is a locked reference: its rows point to the account that
        # stays. Erase that account instead.
        if principal.merged_into is not None:
            raise ConflictError(
                "The account is merged into another account. Erase that account instead.",
                code="erase_merged",
            )
        address = principal.email
        principal.email = None
        principal.display_name = None
        principal.calendar_token = None
        principal.oidc_groups = None
        principal.active = False
        # Without groups the principal holds no gremium membership any more.
        await sync_principal_memberships(self.session, principal)
        # The reason of an excuse is personal data (Z2). The attendance status stays,
        # because the protocols carry it. Only the rows with a reason change, so an
        # older (self, absent) row does not meet the self-status check.
        await self.session.execute(
            update(MeetingAttendance)
            .where(
                MeetingAttendance.principal_id == principal_id,
                MeetingAttendance.note.is_not(None),
            )
            .values(note=None)
        )
        # F2: the name of a candidacy in an election, and its copies in the protocol
        # text, unless the principal was elected (a documented resolution).
        erased = await erase_candidacies(self.session, principal_id)
        await erase_candidate_names(self.session, erased)
        await anonymize_reported_tickets(
            self.session, actor=actor, files=files, principal_id=principal_id, email=address
        )
        await erase_sender_blocks(self.session, principal_id=principal_id, email=address)
        storage_keys = await erase_todos(self.session, principal_id, files=files, actor=actor)
        await self.session.execute(
            delete(AuthSession).where(AuthSession.principal_id == principal_id)
        )
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.PRINCIPAL_ERASED,
            target_type="principal",
            target_id=str(principal_id),
        )
        if commit:
            await self.session.commit()
            if files is not None:
                await files.remove_objects(storage_keys)
        else:
            await self.session.flush()
            self.storage_keys.extend(storage_keys)
        return principal


async def anonymize_reported_tickets(
    session: AsyncSession,
    *,
    actor: str,
    files: FilesService | None = None,
    principal_id: UUID | None = None,
    email: str | None = None,
) -> int:
    """Anonymize the tickets of one reporter, without a commit.

    A ticket matches when the account reported it (``principal_id``) or when a report
    without a session gave the address (``email``, a citext compare). Already
    anonymized tickets do not change.

    The tickets are read ``FOR UPDATE``, in id order, as ``add_note`` and the
    retention cron read them. A note that binds files waits for the anonymization or
    finishes before it, because otherwise its files stay on an anonymized ticket that
    no later step cleans up.

    Returns:
        The number of anonymized tickets.
    """
    reporter: list[ColumnElement[bool]] = []
    if principal_id is not None:
        reporter.append(Ticket.reporter_principal_id == principal_id)
    if email:
        reporter.append(Ticket.reporter_email == email)
    if not reporter:
        return 0
    reported = (
        await session.scalars(
            select(Ticket)
            .where(or_(*reporter), Ticket.anonymized_at.is_(None))
            .order_by(Ticket.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    tickets = TicketService(session, files=files or FilesService(session))
    for ticket in reported:
        await tickets.anonymize(ticket, actor=actor)
    return len(reported)


async def erase_email(
    session: AsyncSession,
    email: str,
    *,
    actor: str,
    files: FilesService | None = None,
) -> dict[str, Any]:
    """Erase the data of one e-mail address that has no account behind it, and commit.

    A person can reach the platform without an account: as an applicant, or as the
    reporter of a ticket without a session. Neither path files an erasure request
    for a ticket, so this is the erasure for such an address. Every application
    whose applicant has the address gets the applicant anonymization, and every
    ticket with the address as ``reporter_email`` gets the ticket anonymization. The
    compare is citext, as in the Auskunft. Rows that are already anonymized do not
    change. A sender block of the address goes.

    An account under the address stays: its erasure deactivates the account, so it
    stays a separate step. ``principalId`` names that account.

    The audit entry holds the counts and no address, because the address is the data
    that goes.

    Returns:
        ``applications`` and ``tickets`` (the anonymized counts) and ``principalId``.
    """
    app_ids = list(
        (
            await session.scalars(
                select(Applicant.application_id).where(
                    Applicant.email == email, Applicant.anonymized_at.is_(None)
                )
            )
        ).all()
    )
    applications = ApplicationsService(session)
    for application_id in app_ids:
        await applications.anonymize(
            application_id, files=files, actor=actor, commit=False
        )
        await audit_record(
            session,
            actor=actor,
            action=AuditAction.ANONYMIZATION,
            target_type="application",
            target_id=str(application_id),
        )
    tickets = await anonymize_reported_tickets(
        session, actor=actor, files=files, email=email
    )
    await erase_sender_blocks(session, email=email)
    principal_id = await session.scalar(
        select(Principal.id).where(Principal.email == email)
    )
    await audit_record(
        session,
        actor=actor,
        action=AuditAction.ERASURE_EXECUTED,
        target_type="email",
        data={"applications": len(app_ids), "tickets": tickets},
    )
    await session.commit()
    return {
        "applications": len(app_ids),
        "tickets": tickets,
        "principalId": principal_id,
    }


class PrivacySettingsService:
    """Single-row config: global retention default in months."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> PrivacySettings:
        settings = await self.session.get(PrivacySettings, 1)
        if settings is None:
            # If the migration seed row is missing (fresh schema), create it.
            settings = PrivacySettings(id=1)
            self.session.add(settings)
            await self.session.flush()
        return settings

    async def update(self, *, default_retention_months: int) -> PrivacySettings:
        settings = await self.get()
        settings.default_retention_months = default_retention_months
        await self.session.commit()
        await self.session.refresh(settings)
        return settings


class ErasureRequestService:
    """Erasure-request queue (GDPR Art. 17): open -> executed | rejected."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        subject_type: str,
        application_id: UUID | None = None,
        principal_id: UUID | None = None,
        email: str | None = None,
        requested_by: str | None = None,
    ) -> ErasureRequest:
        if subject_type == "applicant" and application_id is None:
            raise ValidationProblem("applicant erasure requires an application_id")
        if subject_type == "principal" and principal_id is None:
            raise ValidationProblem("principal erasure requires a principal_id")
        # Check the row first so a bad FK gives a 404, not a 500 on flush.
        if (
            application_id is not None
            and await self.session.get(Application, application_id) is None
        ):
            raise NotFoundError(f"application {application_id} not found")
        if subject_type == "applicant" and email is None and application_id is not None:
            # Capture the applicant email now. Anonymization nulls it, but the
            # confirmation mail still needs it.
            email = await self.session.scalar(
                select(Applicant.email).where(
                    Applicant.application_id == application_id
                )
            )
        request = ErasureRequest(
            subject_type=subject_type,
            application_id=application_id,
            principal_id=principal_id,
            email=email,
            status="open",
            requested_by=requested_by,
        )
        self.session.add(request)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=requested_by or "applicant",
            action=AuditAction.ERASURE_REQUESTED,
            target_type="erasure_request",
            target_id=str(request.id),
            data={"subjectType": subject_type},
        )
        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def list(self, *, status: str | None = None) -> list[ErasureRequest]:
        stmt = select(ErasureRequest).order_by(ErasureRequest.created_at.desc())
        if status is not None:
            stmt = stmt.where(ErasureRequest.status == status)
        return list((await self.session.scalars(stmt)).all())

    async def get(self, request_id: UUID) -> ErasureRequest | None:
        return await self.session.get(ErasureRequest, request_id)

    async def _require_open(self, request_id: UUID) -> ErasureRequest:
        request = await self.get(request_id)
        if request is None:
            raise NotFoundError(f"erasure request {request_id} not found")
        if request.status != "open":
            raise ConflictError(
                f"erasure request already {request.status}", code="erasure_not_open"
            )
        return request

    async def execute(
        self, request_id: UUID, *, actor: str, files: FilesService | None = None
    ) -> ErasureRequest:
        """Execute the request and change the status in the same transaction.

        The service anonymizes the application or erases the principal. If `files`
        carries an object storage, the service also removes the attachment objects.

        Raises:
            NotFoundError: No erasure request has this id.
            ConflictError: The request is not open, or it has no resolvable subject.
        """
        request = await self._require_open(request_id)
        storage_keys: list[str] = []
        if request.subject_type == "applicant" and request.application_id is not None:
            await ApplicationsService(self.session).anonymize(
                request.application_id, files=files, actor=actor, commit=False
            )
            await audit_record(
                self.session,
                actor=actor,
                action=AuditAction.ANONYMIZATION,
                target_type="application",
                target_id=str(request.application_id),
            )
            # The applicant can also have reported a ticket without a session under
            # the same address; the Auskunft lists those tickets, so they go too.
            await anonymize_reported_tickets(
                self.session, actor=actor, files=files, email=request.email
            )
            await erase_sender_blocks(self.session, email=request.email)
        elif request.subject_type == "principal" and request.principal_id is not None:
            principals = PrincipalService(self.session)
            await principals.erase(request.principal_id, actor=actor, commit=False, files=files)
            storage_keys = principals.storage_keys
        else:
            raise ConflictError(
                "erasure request has no resolvable subject", code="erasure_no_subject"
            )
        request.status = "executed"
        request.handled_by = actor
        request.handled_at = _now()
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.ERASURE_EXECUTED,
            target_type="erasure_request",
            target_id=str(request.id),
        )
        await self.session.commit()
        if files is not None:
            await files.remove_objects(storage_keys)
        await self.session.refresh(request)
        return request

    async def reject(
        self, request_id: UUID, *, actor: str, reason: str | None = None
    ) -> ErasureRequest:
        request = await self._require_open(request_id)
        request.status = "rejected"
        request.handled_by = actor
        request.handled_at = _now()
        request.reason = reason
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.ERASURE_REJECTED,
            target_type="erasure_request",
            target_id=str(request.id),
        )
        await self.session.commit()
        await self.session.refresh(request)
        return request


class AuskunftService:
    """GDPR access request (Art. 15): gather all PII stored for an email."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def collect(self, email: str, *, locale: str = "de") -> dict[str, Any]:
        """Gather every record that the platform stores for one email address.

        The result holds the applicants and their applications with data and version
        history. It also holds the comments that the subject can see, the attachment
        metadata, and the matching principal.

        Returns:
            Rows ready for `build_auskunft_workbook`.
        """
        applicants = list(
            (
                await self.session.scalars(
                    select(Applicant).where(Applicant.email == email)
                )
            ).all()
        )
        applicant_by_app = {a.application_id: a for a in applicants}
        app_ids = list(applicant_by_app.keys())

        applications: list[dict[str, Any]] = []
        versions: list[dict[str, Any]] = []
        comments: list[dict[str, Any]] = []
        attachments: list[dict[str, Any]] = []
        if app_ids:
            apps = list(
                (
                    await self.session.scalars(
                        select(Application).where(Application.id.in_(app_ids))
                    )
                ).all()
            )
            type_ids = {a.type_id for a in apps}
            type_names = {
                tid: name
                for tid, name in (
                    await self.session.execute(
                        select(ApplicationType.id, ApplicationType.name_i18n).where(
                            ApplicationType.id.in_(type_ids)
                        )
                    )
                ).all()
            }
            state_ids = {a.current_state_id for a in apps if a.current_state_id}
            state_labels = (
                {
                    sid: label
                    for sid, label in (
                        await self.session.execute(
                            select(State.id, State.label_i18n).where(
                                State.id.in_(state_ids)
                            )
                        )
                    ).all()
                }
                if state_ids
                else {}
            )
            for a in apps:
                applicant = applicant_by_app.get(a.id)
                applications.append(
                    {
                        "id": a.id,
                        "typeName": _i18n(type_names.get(a.type_id), locale),
                        "status": _i18n(
                            state_labels.get(a.current_state_id)
                            if a.current_state_id is not None
                            else None,
                            locale,
                        ),
                        "createdAt": a.created_at,
                        "applicantName": applicant.name if applicant else "",
                        "data": a.data,
                    }
                )
            vrows = list(
                (
                    await self.session.scalars(
                        select(SubmissionVersion)
                        .where(SubmissionVersion.application_id.in_(app_ids))
                        .order_by(
                            SubmissionVersion.application_id, SubmissionVersion.version
                        )
                    )
                ).all()
            )
            versions = [
                {
                    "applicationId": v.application_id,
                    "version": v.version,
                    "changedBy": v.changed_by,
                    "at": v.at,
                    "data": v.data,
                }
                for v in vrows
            ]

            # Restrict the result to the comments that the subject can see. These are
            # the comments of the subject (author_kind='applicant') and the comments
            # with visibility 'public'. The query excludes internal principal notes.
            crows = list(
                (
                    await self.session.scalars(
                        select(Comment)
                        .where(
                            Comment.application_id.in_(app_ids),
                            or_(
                                Comment.author_kind == "applicant",
                                Comment.visibility == "public",
                            ),
                        )
                        .order_by(Comment.application_id, Comment.at)
                    )
                ).all()
            )
            names: dict[UUID, list[str]] = {}
            if crows:
                for comment_id, filename in (
                    await self.session.execute(
                        select(Attachment.comment_id, Attachment.filename)
                        .where(Attachment.comment_id.in_([c.id for c in crows]))
                        .order_by(Attachment.created_at, Attachment.id)
                    )
                ).all():
                    names.setdefault(cast(UUID, comment_id), []).append(filename)
            comments = [
                {
                    "applicationId": c.application_id,
                    "authorKind": c.author_kind,
                    "visibility": c.visibility,
                    "body": c.body,
                    "at": c.at,
                    "attachments": names.get(c.id, []),
                }
                for c in crows
            ]

            # Attachment metadata only. A filename can be PII. The export holds no
            # binary object.
            arows = list(
                (
                    await self.session.scalars(
                        select(Attachment)
                        .where(
                            Attachment.application_id.is_not(None),
                            Attachment.application_id.in_(app_ids),
                        )
                        .order_by(Attachment.application_id, Attachment.created_at)
                    )
                ).all()
            )
            attachments = [
                {
                    "applicationId": at.application_id,
                    "filename": at.filename,
                    "mime": at.mime,
                    "size": at.size,
                    "createdAt": at.created_at,
                }
                for at in arows
            ]

        # Several rows can share the address: an account that was merged into a newer
        # one keeps its email (account merge). The live account comes first: not
        # merged, then active, then the newest login.
        principal_row = await self.session.scalar(
            select(Principal)
            .where(Principal.email == email)
            .order_by(
                Principal.merged_into.is_not(None),
                Principal.active.is_(False),
                Principal.last_login.desc().nulls_last(),
            )
            .limit(1)
        )
        attendance: list[dict[str, Any]] = []
        if principal_row is not None:
            # The attendance of the principal, with the reason of an excuse (Z2).
            arows = (
                await self.session.execute(
                    select(MeetingAttendance, Meeting)
                    .join(Meeting, Meeting.id == MeetingAttendance.meeting_id)
                    .where(MeetingAttendance.principal_id == principal_row.id)
                    .order_by(Meeting.date, Meeting.id)
                )
            ).all()
            attendance = [
                {
                    "meetingId": meeting.id,
                    "meetingTitle": meeting.title,
                    "meetingDate": meeting.date,
                    "status": rec.status,
                    "source": rec.source,
                    "note": rec.note,
                }
                for rec, meeting in arows
            ]
        # The tickets that the address reported: as the e-mail of a report without a
        # session, or through the account.
        reporter = [Ticket.reporter_email == email]
        if principal_row is not None:
            reporter.append(Ticket.reporter_principal_id == principal_row.id)
        trows = (
            await self.session.scalars(
                select(Ticket).where(or_(*reporter)).order_by(Ticket.number)
            )
        ).all()
        tickets = [
            {
                "number": format_number(t.number),
                "title": t.title,
                "status": t.status,
                "createdAt": t.created_at,
                "body": t.body,
                "context": t.context,
            }
            for t in trows
        ]
        if trows:
            # The attachments of the reported tickets: metadata only, as above.
            number_by_ticket = {t.id: format_number(t.number) for t in trows}
            tarows = (
                await self.session.scalars(
                    select(Attachment)
                    .where(Attachment.ticket_id.in_(list(number_by_ticket)))
                    .order_by(Attachment.ticket_id, Attachment.created_at)
                )
            ).all()
            attachments.extend(
                {
                    "ticketNumber": number_by_ticket.get(at.ticket_id) if at.ticket_id else None,
                    "filename": at.filename,
                    "mime": at.mime,
                    "size": at.size,
                    "createdAt": at.created_at,
                }
                for at in tarows
            )
        todos = await todo_export(
            self.session, [principal_row.id] if principal_row is not None else []
        )
        blocks = [
            {
                "kind": "principal" if b.principal_id is not None else "email",
                "createdAt": b.created_at,
                "hitCount": b.hit_count,
                "lastHitAt": b.last_hit_at,
            }
            for b in await sender_blocks_of(
                self.session,
                principal_id=principal_row.id if principal_row is not None else None,
                email=email,
            )
        ]
        principal = (
            {
                "sub": principal_row.sub,
                "email": principal_row.email,
                "displayName": principal_row.display_name,
                "active": principal_row.active,
                "lastLogin": principal_row.last_login,
            }
            if principal_row is not None
            else None
        )
        return {
            "email": email,
            "applications": applications,
            "versions": versions,
            "comments": comments,
            "attachments": attachments,
            "attendance": attendance,
            "tickets": tickets,
            "todos": todos["cards"],
            "todo_comments": todos["comments"],
            "sender_blocks": blocks,
            "principal": principal,
        }


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else ""


def build_auskunft_workbook(
    *,
    email: str,
    applications: Sequence[Mapping[str, Any]],
    versions: Sequence[Mapping[str, Any]],
    principal: Mapping[str, Any] | None,
    comments: Sequence[Mapping[str, Any]] = (),
    attachments: Sequence[Mapping[str, Any]] = (),
    attendance: Sequence[Mapping[str, Any]] = (),
    tickets: Sequence[Mapping[str, Any]] = (),
    todos: Sequence[Mapping[str, Any]] = (),
    todo_comments: Sequence[Mapping[str, Any]] = (),
    sender_blocks: Sequence[Mapping[str, Any]] = (),
) -> bytes:
    """Build the GDPR access request (Art. 15) as `.xlsx` bytes.

    This function extends the shared `app.shared.xlsx.build_auskunft_workbook`. It adds
    seven sheets: the comments that the subject can see (with the names of their
    files), the attachment metadata of the applications and the reported tickets, the
    meeting attendance with the reason of an excuse, the reported tickets with their
    text and technical context, the to-dos that the subject created or is assigned to
    (with the description of the own cards), the own to-do comments (with the names of
    their files), and the sender blocks of the account or the address.
    """
    from io import BytesIO

    from openpyxl import load_workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    from app.shared.xlsx import _safe
    from app.shared.xlsx import build_auskunft_workbook as _build_base

    base = _build_base(
        email=email,
        applications=applications,
        versions=versions,
        principal=principal,
    )
    wb = load_workbook(BytesIO(base))

    def _add_sheet(
        title: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> None:
        ws = wb.create_sheet(title=title)
        ws.append([_safe(h) for h in headers])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for row in rows:
            # Neutralize formula injection in applicant-supplied text such as a
            # comment body or a filename. The shared base sheets get the same
            # protection from app.shared.xlsx._safe.
            ws.append([_safe(cell) for cell in row])
        widths = [len(str(h)) for h in headers]
        for r in ws.iter_rows(min_row=2, values_only=True):
            for i, cell in enumerate(r):
                widths[i] = max(widths[i], len(str(cell)) if cell is not None else 0)
        for i, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)

    _add_sheet(
        "Kommentare",
        ["Antrags-ID", "Autor-Art", "Sichtbarkeit", "Zeitpunkt", "Text", "Anhänge"],
        [
            [
                str(c.get("applicationId") or ""),
                c.get("authorKind") or "",
                c.get("visibility") or "",
                _fmt_dt(c.get("at")),
                c.get("body") or "",
                "; ".join(c.get("attachments") or []),
            ]
            for c in comments
        ],
    )
    _add_sheet(
        "Anhänge",
        ["Antrag / Ticket", "Dateiname", "Typ", "Größe (Bytes)", "Hochgeladen"],
        [
            [
                str(at.get("applicationId") or at.get("ticketNumber") or ""),
                at.get("filename") or "",
                at.get("mime") or "",
                at.get("size"),
                _fmt_dt(at.get("createdAt")),
            ]
            for at in attachments
        ],
    )
    _add_sheet(
        "Anwesenheit",
        ["Sitzungs-ID", "Sitzung", "Datum", "Status", "Erfasst durch", "Grund"],
        [
            [
                str(a.get("meetingId") or ""),
                a.get("meetingTitle") or "",
                a["meetingDate"].isoformat() if a.get("meetingDate") else "",
                a.get("status") or "",
                a.get("source") or "",
                a.get("note") or "",
            ]
            for a in attendance
        ],
    )

    _add_sheet(
        "Tickets",
        ["Nummer", "Titel", "Status", "Gemeldet", "Text", "Technischer Kontext"],
        [
            [
                t.get("number") or "",
                t.get("title") or "",
                t.get("status") or "",
                _fmt_dt(t.get("createdAt")),
                t.get("body") or "",
                json.dumps(t["context"], ensure_ascii=False, sort_keys=True)
                if t.get("context")
                else "",
            ]
            for t in tickets
        ],
    )
    _add_sheet(
        "To-Dos",
        ["Board", "Titel", "Spalte", "Fällig", "Erstellt", "Beschreibung"],
        [
            [
                t.get("board") or "",
                t.get("title") or "",
                t.get("column") or "",
                t["dueDate"].isoformat() if t.get("dueDate") else "",
                _fmt_dt(t.get("createdAt")),
                t.get("description") or "",
            ]
            for t in todos
        ],
    )
    _add_sheet(
        "To-Do-Kommentare",
        ["To-Do", "Zeitpunkt", "Gelöscht", "Text", "Anhänge"],
        [
            [
                c.get("card") or "",
                _fmt_dt(c.get("createdAt")),
                _fmt_dt(c.get("deletedAt")),
                c.get("body") or "",
                "; ".join(c.get("attachments") or []),
            ]
            for c in todo_comments
        ],
    )
    _add_sheet(
        "Ticket-Sperren",
        ["Art", "gesperrt am", "abgefangene Meldungen", "letzter Versuch"],
        [
            [
                "Konto" if b.get("kind") == "principal" else "E-Mail-Adresse",
                _fmt_dt(b.get("createdAt")),
                b.get("hitCount") or 0,
                _fmt_dt(b.get("lastHitAt")),
            ]
            for b in sender_blocks
        ],
    )

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
