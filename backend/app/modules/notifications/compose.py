"""Build one branded mail: the plain text, the HTML frame, the sender and the logo.

Every sender of the platform builds its `MailMessage` here, so no mail misses a part of
the branding (§ F/collaboration/notifications/000998 to 001004). The plain-text part
gets the link line and the footer text. The HTML part gets the frame of `layout`. The
sender name is the platform name of the branding. The logo of the frame goes with the
mail as an inline part.
"""

from __future__ import annotations

from app.modules.notifications.brand import LOGO_CID, MailBrand
from app.modules.notifications.layout import (
    append_brand_text,
    append_link_text,
    reason_text,
    render_layout,
    text_to_html,
)
from app.modules.notifications.links import MailLink
from app.modules.notifications.mail import MailAttachment, MailInline, MailMessage
from app.settings import Settings


def branded_mail(
    *,
    brand: MailBrand,
    settings: Settings,
    to: tuple[str, ...],
    subject: str,
    text: str,
    reason: str,
    lang: str,
    idempotency_key: str,
    html: str | None = None,
    link: MailLink | None = None,
    attachments: tuple[MailAttachment, ...] = (),
    reply_to: str | None = None,
) -> MailMessage:
    """Return the mail for a rendered subject and body.

    ``html`` is the safe inner HTML of a template. Without it the frame escapes and wraps
    ``text``. The HTML comes from the text before the link line, so the HTML shows the
    link as a button only. ``reason`` is the mail kind of the footer hint. ``reply_to``
    sets the Reply-To header.
    """
    base_url = settings.public_base_url
    with_link = append_link_text(text, link.url, link.label(lang)) if link is not None else text
    return MailMessage(
        to=to,
        subject=subject,
        text=append_brand_text(with_link, brand, lang, base_url),
        html=render_layout(
            content_html=html or text_to_html(text),
            title=subject,
            brand=brand,
            base_url=base_url,
            reason=reason_text(reason, lang, brand.name),
            lang=lang,
            action_url=link.url if link is not None else None,
            action_label=link.label(lang) if link is not None else None,
        ),
        idempotency_key=idempotency_key,
        from_name=brand.name,
        attachments=attachments,
        reply_to=reply_to,
        inline=(
            (MailInline(cid=LOGO_CID, mime="image/png", content=brand.logo.png),)
            if brand.logo is not None
            else ()
        ),
    )
