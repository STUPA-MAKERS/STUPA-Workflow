"""The mail to the applicant of an application captured on their behalf (#11).

A person with ``application.create_on_behalf`` entered the application. The applicant
gets one mail with a link:

- An applicant account gets the normal link to the application
  (``/applications/{id}``). The login is the usual one.
- A guest applicant gets a magic link (``/antrag/{id}#t=…``), as after a guest
  submission. The link comes from ``auth.service.request_magic_link``, so the token
  rules are the same.

The mail is not opt-outable: its kind is not in ``NOTIFICATION_KINDS``, like the magic
link. It is the only notice that an application in the name of the person exists.

The send runs as a background task after the commit, in its own session. It is best
effort: a failure logs and never breaks the request.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.db import get_sessionmaker
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import (
    NotificationService,
    resolve_application_lang,
)
from app.settings import Settings

logger = logging.getLogger("app.notifications")

#: The template key and the footer kind of the mail.
APPLICATION_CAPTURED_KEY = "application_captured"

APPLICATION_CAPTURED_SUBJECT: dict[str, str] = {
    "de": "Für dich wurde ein Antrag erfasst"
    "{% if applicationTitle %}: „{{ applicationTitle }}“{% endif %}",
    "en": "An application was entered for you"
    '{% if applicationTitle %}: "{{ applicationTitle }}"{% endif %}',
}
APPLICATION_CAPTURED_BODY: dict[str, str] = {
    "de": "Hallo{% if applicantName %} {{ applicantName }}{% endif %},\n\n"
    "für dich wurde ein Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %} "
    "auf der Antragsplattform erfasst"
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}."
    "{% if receivedOn %} Eingegangen am {{ receivedOn }}.{% endif %}"
    "{% if intake %} Eingang: {{ intake }}.{% endif %}\n\n"
    "Der Antrag gehört dir. Du kannst ihn hier ansehen und verfolgen:\n{{ link }}\n"
    "{% if isGuest %}\nDer Link ist dein persönlicher Zugang. Gib ihn nicht weiter.\n"
    "{% else %}\nMelde dich mit deinem Konto an, um den Antrag zu öffnen.\n{% endif %}",
    "en": "Hello{% if applicantName %} {{ applicantName }}{% endif %},\n\n"
    "an application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %} '
    "was entered for you on the application platform"
    "{% if gremiumName %} ({{ gremiumName }}){% endif %}."
    "{% if receivedOn %} Received on {{ receivedOn }}.{% endif %}"
    "{% if intake %} Intake: {{ intake }}.{% endif %}\n\n"
    "The application is yours. You can view and follow it here:\n{{ link }}\n"
    "{% if isGuest %}\nThe link is your personal access. Do not share it.\n"
    "{% else %}\nSign in with your account to open the application.\n{% endif %}",
}

#: The placeholders of the template editor.
APPLICATION_CAPTURED_PLACEHOLDERS: dict[str, str] = {
    "applicationTitle": "Titel des Antrags",
    "applicantName": "Name der antragstellenden Person",
    "gremiumName": "Gremium des Antrags",
    "receivedOn": "Eingangsdatum",
    "intake": "Eingang (zum Beispiel „per PDF“)",
    "link": "Link zum Antrag (Konto) oder Zugangslink (Gast)",
    "isGuest": "Wahr bei einem Gast ohne Konto",
    "applicationId": "ID des Antrags",
}


def _format_date(value: date | None, lang: str) -> str:
    """Return the date as ``05.10.2026`` (de) or ``2026-10-05`` (en)."""
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y") if lang == "de" else value.isoformat()


async def notify_application_captured(
    *,
    queue: MailQueue | None,
    settings: Settings,
    application_id: UUID,
    email: str,
    guest: bool,
) -> None:
    """Send the mail to the applicant of a captured application.

    ``guest`` selects the link: a magic link for a guest, the normal link for an
    account. The idempotency key holds only the application, so a retry or a second
    call for the same application coalesces into one mail.
    """
    from app.modules.admin.models import Gremium
    from app.modules.applications.models import Applicant, Application
    from app.modules.auth import service as auth_service

    try:
        async with get_sessionmaker()() as session:
            app = await session.get(Application, application_id)
            if app is None:
                return
            name = await session.scalar(
                select(Applicant.name).where(Applicant.application_id == application_id)
            )
            gremium = (
                await session.get(Gremium, app.gremium_id) if app.gremium_id else None
            )
            lang = await resolve_application_lang(
                session, application_id=application_id, settings=settings
            )
            title = app.data.get("title") if isinstance(app.data, dict) else None
            context: dict[str, object] = {
                "applicationTitle": str(title) if title else "",
                "applicantName": name or "",
                "gremiumName": gremium.name if gremium is not None else "",
                "receivedOn": _format_date(app.received_on, lang),
                "intake": app.capture_intake or "",
                "isGuest": guest,
                "applicationId": str(application_id),
            }
            service = NotificationService(session, queue=queue, settings=settings)

            async def deliver(recipient: str, link: str) -> None:
                await service.send_kind_mail(
                    [recipient],
                    kind=APPLICATION_CAPTURED_KEY,
                    template_key=APPLICATION_CAPTURED_KEY,
                    builtin_subject=APPLICATION_CAPTURED_SUBJECT,
                    builtin_body=APPLICATION_CAPTURED_BODY,
                    context={**context, "link": link},
                    idempotency_parts=(APPLICATION_CAPTURED_KEY, str(application_id)),
                    lang=lang,
                )

            if guest:
                await auth_service.request_magic_link(
                    session,
                    settings,
                    email=email,
                    application_id=application_id,
                    deliver=deliver,
                )
                await session.commit()
            else:
                base = settings.public_base_url.rstrip("/")
                await deliver(email, f"{base}/applications/{application_id}")
    except Exception:  # best effort: a mail failure never breaks the request
        logger.exception("application_captured mail failed (application=%s)", application_id)
