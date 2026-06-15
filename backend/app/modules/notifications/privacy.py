"""DSGVO-Löschantrags-Mails (#PII-Re-Add): eingegangen/ausgeführt/abgelehnt.

Best-effort versendet als Hintergrund-Task (Privacy-Router bzw. Applicant-Self-
Service). Jeder Versand öffnet seinen eigenen Sessionmaker — die Funktionen laufen
*nach* dem Commit der auslösenden Transaktion. Die Builtin-Betreff/Text-Dicts sind
zugleich die Editor-Defaults (templates_catalogue.py).
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.db import get_sessionmaker
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.service import NotificationService
from app.settings import Settings

logger = logging.getLogger("app.privacy")

ERASURE_REQUESTED_SUBJECT: dict[str, str] = {
    "de": "Neuer Löschantrag (DSGVO Art. 17)",
    "en": "New erasure request (GDPR Art. 17)",
}
ERASURE_REQUESTED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nein Löschantrag ist eingegangen und wartet auf Bearbeitung in "
    "der Datenschutz-Verwaltung (/admin/privacy).\n",
    "en": "Hello,\n\nan erasure request has been received and is awaiting review in "
    "the privacy admin area (/admin/privacy).\n",
}
ERASURE_EXECUTED_SUBJECT: dict[str, str] = {
    "de": "Ihre Daten wurden gelöscht (DSGVO Art. 17)",
    "en": "Your data has been erased (GDPR Art. 17)",
}
ERASURE_EXECUTED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nIhr Löschantrag wurde ausgeführt. Ihre personenbezogenen Daten "
    "wurden gemäß DSGVO Art. 17 anonymisiert bzw. gelöscht.\n",
    "en": "Hello,\n\nyour erasure request has been executed. Your personal data has "
    "been anonymised or erased in accordance with GDPR Art. 17.\n",
}
ERASURE_REJECTED_SUBJECT: dict[str, str] = {
    "de": "Ihr Löschantrag wurde abgelehnt",
    "en": "Your erasure request was rejected",
}
ERASURE_REJECTED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nIhr Löschantrag wurde abgelehnt"
    "{% if reason %}: {{ reason }}{% endif %}.\n",
    "en": "Hello,\n\nyour erasure request was rejected"
    "{% if reason %}: {{ reason }}{% endif %}.\n",
}


async def notify_erasure_requested(
    *,
    queue: MailQueue | None,
    settings: Settings,
    request_id: UUID,
    subject_type: str,
) -> None:
    """Datenschutz-Verantwortliche (``privacy.manage``) über einen neuen Antrag informieren."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        recipients = await RecipientResolver(session).resolve(
            [{"kind": "permission", "ref": "privacy.manage"}]
        )
        if not recipients:
            return
        await NotificationService(
            session, queue=queue, settings=settings
        ).send_kind_mail(
            recipients,
            kind="privacy",
            template_key="erasure_requested",
            builtin_subject=ERASURE_REQUESTED_SUBJECT,
            builtin_body=ERASURE_REQUESTED_BODY,
            context={"subjectType": subject_type, "requestId": str(request_id)},
            idempotency_parts=("erasure_requested", str(request_id)),
        )


async def notify_erasure_executed(
    *,
    queue: MailQueue | None,
    settings: Settings,
    request_id: UUID,
    email: str | None,
    subject_type: str,
) -> None:
    """Die betroffene Person über die Ausführung informieren (sofern Mail bekannt)."""
    if not email:
        return
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await NotificationService(
            session, queue=queue, settings=settings
        ).send_kind_mail(
            [email],
            kind="privacy",
            template_key="erasure_executed",
            builtin_subject=ERASURE_EXECUTED_SUBJECT,
            builtin_body=ERASURE_EXECUTED_BODY,
            context={"subjectType": subject_type, "requestId": str(request_id)},
            idempotency_parts=("erasure_executed", str(request_id)),
        )


async def notify_erasure_rejected(
    *,
    queue: MailQueue | None,
    settings: Settings,
    request_id: UUID,
    email: str | None,
    reason: str | None,
) -> None:
    """Die betroffene Person über die Ablehnung (mit Grund) informieren."""
    if not email:
        return
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await NotificationService(
            session, queue=queue, settings=settings
        ).send_kind_mail(
            [email],
            kind="privacy",
            template_key="erasure_rejected",
            builtin_subject=ERASURE_REJECTED_SUBJECT,
            builtin_body=ERASURE_REJECTED_BODY,
            context={"reason": reason or "", "requestId": str(request_id)},
            idempotency_parts=("erasure_rejected", str(request_id)),
        )
