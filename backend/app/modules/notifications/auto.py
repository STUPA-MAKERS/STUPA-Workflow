"""Auto-Mails für Plattform-Ereignisse (#4-3): Sitzungen, Rollen, Delegationen.

Background-Task-Einstiege (eigene Session, nach der API-Antwort), alle
**best effort**: ein Mail-Fehler darf den auslösenden Request nie brechen —
Exceptions werden geloggt und verworfen. Versand läuft über
:meth:`NotificationService.send_kind_mail` (Präferenz-Filter #4-2, Layout #4,
DB-Template mit Builtin-Fallback).

Status-Update- und Task-Mails je Statuswechsel laufen NICHT hier, sondern als
implizite Flow-Actions (``build_implicit_notifications`` → Notify-Dispatcher).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.db import get_sessionmaker
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.service import NotificationService
from app.settings import Settings

logger = logging.getLogger("app.notifications")

_BUILTIN_MEETING_SUBJECT = {
    "de": "Neue Sitzung: {{ meetingTitle }}"
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}",
    "en": "New meeting: {{ meetingTitle }}"
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}",
}
_BUILTIN_MEETING_BODY = {
    "de": "Hallo,\n\nfür dein Gremium{% if gremiumName %} {{ gremiumName }}"
    "{% endif %} wurde eine Sitzung angesetzt:\n\n{{ meetingTitle }}"
    "{% if meetingDate %}\nDatum: {{ meetingDate }}{% endif %}"
    "{% if meetingTime %}, {{ meetingTime }} Uhr{% endif %}\n",
    "en": "Hello,\n\na meeting was scheduled for your committee"
    "{% if gremiumName %} {{ gremiumName }}{% endif %}:\n\n{{ meetingTitle }}"
    "{% if meetingDate %}\nDate: {{ meetingDate }}{% endif %}"
    "{% if meetingTime %}, {{ meetingTime }}{% endif %}\n",
}

_BUILTIN_ROLE_ASSIGNED_SUBJECT = {
    "de": "Neue Rolle: {{ roleLabel }}",
    "en": "New role: {{ roleLabel }}",
}
_BUILTIN_ROLE_ASSIGNED_BODY = {
    "de": "Hallo,\n\ndir wurde die Rolle „{{ roleLabel }}“"
    "{% if gremiumName %} im Gremium {{ gremiumName }}{% endif %} zugewiesen.\n",
    "en": "Hello,\n\nyou have been assigned the role \"{{ roleLabel }}\""
    "{% if gremiumName %} in committee {{ gremiumName }}{% endif %}.\n",
}
_BUILTIN_ROLE_REVOKED_SUBJECT = {
    "de": "Rolle entzogen: {{ roleLabel }}",
    "en": "Role revoked: {{ roleLabel }}",
}
_BUILTIN_ROLE_REVOKED_BODY = {
    "de": "Hallo,\n\ndie Rolle „{{ roleLabel }}“"
    "{% if gremiumName %} im Gremium {{ gremiumName }}{% endif %} wurde dir "
    "entzogen.\n",
    "en": "Hello,\n\nthe role \"{{ roleLabel }}\""
    "{% if gremiumName %} in committee {{ gremiumName }}{% endif %} was "
    "revoked from you.\n",
}

_BUILTIN_DELEGATION_GRANTED_SUBJECT = {
    "de": "Delegation erhalten: {{ roleLabel }}",
    "en": "Delegation received: {{ roleLabel }}",
}
_BUILTIN_DELEGATION_GRANTED_BODY = {
    "de": "Hallo,\n\ndir wurde die Rolle „{{ roleLabel }}“"
    "{% if gremiumName %} im Gremium {{ gremiumName }}{% endif %} delegiert"
    "{% if delegatedBy %} (von {{ delegatedBy }}){% endif %}.\n",
    "en": "Hello,\n\nthe role \"{{ roleLabel }}\""
    "{% if gremiumName %} in committee {{ gremiumName }}{% endif %} was "
    "delegated to you{% if delegatedBy %} (by {{ delegatedBy }}){% endif %}.\n",
}
_BUILTIN_DELEGATION_REVOKED_SUBJECT = {
    "de": "Delegation widerrufen: {{ roleLabel }}",
    "en": "Delegation revoked: {{ roleLabel }}",
}
_BUILTIN_DELEGATION_REVOKED_BODY = {
    "de": "Hallo,\n\ndie an dich delegierte Rolle „{{ roleLabel }}“"
    "{% if gremiumName %} im Gremium {{ gremiumName }}{% endif %} wurde "
    "widerrufen.\n",
    "en": "Hello,\n\nthe role \"{{ roleLabel }}\" delegated to you"
    "{% if gremiumName %} in committee {{ gremiumName }}{% endif %} was "
    "revoked.\n",
}


@dataclass(frozen=True, slots=True)
class AssignmentMailInfo:
    """Vor dem Versand (bzw. vor dem Löschen) eingesammelte Zuweisungs-Daten."""

    assignment_id: uuid.UUID
    email: str | None
    role_label: str
    gremium_name: str | None
    delegated_by: str | None


async def assignment_mail_info(
    session: object, assignment_id: uuid.UUID
) -> AssignmentMailInfo | None:
    """Mail-relevante Daten einer Rollenzuweisung einsammeln (None = unbekannt).

    Best effort: schlägt die Abfrage fehl (z. B. gefakte Session in Tests),
    fällt nur die Mail aus — nie der auslösende Request."""
    from app.modules.admin.models import Gremium
    from app.modules.auth.models import Principal, Role, RoleAssignment

    try:
        row = (
            await session.execute(  # type: ignore[attr-defined]
                select(
                    Principal.email,
                    Role.name_i18n,
                    Role.key,
                    Gremium.name,
                    RoleAssignment.delegated_by,
                )
                .join(Principal, Principal.id == RoleAssignment.principal_id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .outerjoin(Gremium, Gremium.id == RoleAssignment.gremium_id)
                .where(RoleAssignment.id == assignment_id)
            )
        ).first()
    except Exception:  # noqa: BLE001 — Mail-Info ist best effort
        logger.exception("assignment mail info failed (assignment=%s)", assignment_id)
        return None
    if row is None:
        return None
    email, name_i18n, key, gremium_name, delegated_by = row
    label = key
    if isinstance(name_i18n, dict) and name_i18n:
        label = name_i18n.get("de") or next(iter(name_i18n.values())) or key
    return AssignmentMailInfo(
        assignment_id=assignment_id,
        email=email,
        role_label=label,
        gremium_name=gremium_name,
        delegated_by=delegated_by,
    )


class AutoMailer:
    """Background-Einstiege der Auto-Mails — best effort, eigene Session."""

    async def meeting_created(
        self, settings: Settings, meeting_id: uuid.UUID, pool: object
    ) -> None:
        try:
            await self._meeting_created(settings, meeting_id, pool)
        except Exception:  # noqa: BLE001 — Mail darf den Request nie brechen
            logger.exception("meeting mail failed (meeting=%s)", meeting_id)

    async def assignment_changed(
        self,
        settings: Settings,
        info: AssignmentMailInfo | None,
        *,
        granted: bool,
        pool: object,
    ) -> None:
        try:
            await self._assignment_changed(settings, info, granted=granted, pool=pool)
        except Exception:  # noqa: BLE001
            logger.exception("role/delegation mail failed")

    # ------------------------------------------------------------ internals #
    async def _meeting_created(
        self, settings: Settings, meeting_id: uuid.UUID, pool: object
    ) -> None:
        from app.modules.admin.models import Gremium
        from app.modules.livevote.models import Meeting
        from app.modules.notifications.recipients import RecipientResolver

        queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            meeting = await session.get(Meeting, meeting_id)
            if meeting is None:
                return
            gremium_name = await session.scalar(
                select(Gremium.name).where(Gremium.id == meeting.gremium_id)
            )
            recipients = await RecipientResolver(session).resolve(
                [{"kind": "gremium", "ref": str(meeting.gremium_id)}]
            )
            service = NotificationService(session, queue=queue, settings=settings)
            await service.send_kind_mail(
                recipients,
                kind="meeting",
                template_key="meeting_created",
                builtin_subject=_BUILTIN_MEETING_SUBJECT,
                builtin_body=_BUILTIN_MEETING_BODY,
                context={
                    "meetingId": str(meeting.id),
                    "meetingTitle": meeting.title,
                    "meetingDate": meeting.date.strftime("%d.%m.%Y")
                    if meeting.date
                    else "",
                    "meetingTime": meeting.start_time.strftime("%H:%M")
                    if meeting.start_time
                    else "",
                    "gremiumName": gremium_name or "",
                },
                idempotency_parts=("meeting_created", str(meeting.id)),
            )

    async def _assignment_changed(
        self,
        settings: Settings,
        info: AssignmentMailInfo | None,
        *,
        granted: bool,
        pool: object,
    ) -> None:
        if info is None or not info.email:
            return
        is_delegation = info.delegated_by is not None
        if is_delegation:
            kind = "delegation"
            template_key = (
                "delegation_granted" if granted else "delegation_revoked"
            )
            builtin = (
                (_BUILTIN_DELEGATION_GRANTED_SUBJECT, _BUILTIN_DELEGATION_GRANTED_BODY)
                if granted
                else (
                    _BUILTIN_DELEGATION_REVOKED_SUBJECT,
                    _BUILTIN_DELEGATION_REVOKED_BODY,
                )
            )
        else:
            kind = "role_change"
            template_key = "role_assigned" if granted else "role_revoked"
            builtin = (
                (_BUILTIN_ROLE_ASSIGNED_SUBJECT, _BUILTIN_ROLE_ASSIGNED_BODY)
                if granted
                else (_BUILTIN_ROLE_REVOKED_SUBJECT, _BUILTIN_ROLE_REVOKED_BODY)
            )
        queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = NotificationService(session, queue=queue, settings=settings)
            await service.send_kind_mail(
                [info.email],
                kind=kind,
                template_key=template_key,
                builtin_subject=builtin[0],
                builtin_body=builtin[1],
                context={
                    "roleLabel": info.role_label,
                    "gremiumName": info.gremium_name or "",
                    "delegatedBy": info.delegated_by or "",
                },
                idempotency_parts=(
                    template_key,
                    str(info.assignment_id),
                ),
            )


def get_auto_mailer() -> AutoMailer:
    """Injizierbarer Auto-Mailer (in Tests überschreibbar)."""
    return AutoMailer()
