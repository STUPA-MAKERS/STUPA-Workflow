"""Branded HTML mail layout: one frame in code, the content from templates.

The layout wraps every outgoing mail in the same frame. The frame holds a
header with the logo or the name of the platform, a content card, and a footer.
The footer shows the trigger hint, the footer text of the branding, a link to
the notification settings, the legal links and the copyright line. DB templates
provide only the **inner** content. When a template has no HTML body, the code
escapes and wraps the text body. A text-only template therefore still gets a
usable HTML alternative.

The name, the logo, the accent colour and the footer come from the branding
(`brand`, § F/collaboration/notifications/000998 to 001003).

The layout uses inline CSS for the light colours because some mail clients
ignore <style>. A <style> block holds only the dark colours
(§ F/collaboration/notifications/001004): a client that ignores it shows the
light mail. The layout loads no external resources: the logo is an inline part
of the mail, and the frame shows it by its content id.
"""

from __future__ import annotations

import html
import re

from app.modules.notifications.brand import LOGO_CID, MailBrand, brand_text
from app.modules.notifications.colours import DARK, LIGHT, on_fill, readable
from app.shared.i18n import pick_lang

#: The place of the platform name in a footer reason.
_NAME = "{name}"

#: Footer reason per mail kind ("you receive this email because ...").
_REASONS: dict[str, dict[str, str]] = {
    "magic_link": {
        "de": "Sie erhalten diese E-Mail, weil für Ihre Adresse ein Zugangslink angefordert wurde.",
        "en": "You are receiving this email because an access link was requested for your address.",
    },
    "application_captured": {
        "de": "Sie erhalten diese E-Mail, weil für Sie ein Antrag bei {name} erfasst wurde.",
        "en": "You are receiving this email because an application was entered for you on {name}.",
    },
    "application_observer_added": {
        "de": "Sie erhalten diese E-Mail, weil Sie jemand als Beobachter:in eines "
        "Antrags eingetragen hat.",
        "en": "You are receiving this email because someone added you as an observer "
        "of an application.",
    },
    "status_update": {
        "de": "Sie erhalten diese E-Mail, weil sich der Status eines Antrags "
        "geändert hat, der Sie betrifft.",
        "en": "You are receiving this email because the status of an "
        "application that concerns you changed.",
    },
    "comment": {
        "de": "Sie erhalten diese E-Mail, weil es einen neuen Kommentar zu "
        "einem Antrag gibt, der Sie betrifft.",
        "en": "You are receiving this email because there is a new comment "
        "on an application that concerns you.",
    },
    "protocol": {
        "de": "Sie erhalten diese E-Mail, weil ein Sitzungsprotokoll Ihres "
        "Gremiums finalisiert wurde.",
        "en": "You are receiving this email because a meeting protocol of "
        "your committee was finalized.",
    },
    "task": {
        "de": "Sie erhalten diese E-Mail, weil ein Antrag einen Schritt "
        "erreicht hat, in dem Sie handeln können.",
        "en": "You are receiving this email because an application reached "
        "a step where you can act.",
    },
    "meeting": {
        "de": "Sie erhalten diese E-Mail, weil eine Sitzung eines Ihrer "
        "Gremien angesetzt oder geändert wurde.",
        "en": "You are receiving this email because a meeting of one of "
        "your committees was scheduled or changed.",
    },
    "delegation": {
        "de": "Sie erhalten diese E-Mail, weil eine Stimm-Delegation "
        "erteilt oder widerrufen wurde, die Sie betrifft.",
        "en": "You are receiving this email because a vote delegation that "
        "concerns you was granted or revoked.",
    },
    "ticket_created": {
        "de": "Sie erhalten diese E-Mail, weil Sie gemeldete Tickets bearbeiten.",
        "en": "You are receiving this email because you work on reported tickets.",
    },
    "ticket_message": {
        "de": "Sie erhalten diese E-Mail, weil Sie gemeldete Tickets bearbeiten.",
        "en": "You are receiving this email because you work on reported tickets.",
    },
    "ticket_answer": {
        "de": "Sie erhalten diese E-Mail, weil Sie dieses Ticket gemeldet haben.",
        "en": "You are receiving this email because you reported this ticket.",
    },
    "ticket_assigned": {
        "de": "Sie erhalten diese E-Mail, weil Ihnen ein Ticket zugewiesen wurde.",
        "en": "You are receiving this email because a ticket was assigned to you.",
    },
    "ticket_received": {
        "de": "Sie erhalten diese E-Mail, weil Sie ein Problem, eine Frage oder "
        "eine Idee gemeldet haben.",
        "en": "You are receiving this email because you reported a problem, a question or an idea.",
    },
    "gremium_message": {
        "de": "Sie erhalten diese E-Mail, weil Sie Mitglied in diesem Gremium sind.",
        "en": "You are receiving this email because you are a member of this committee.",
    },
    "appointment": {
        "de": "Sie erhalten diese E-Mail, weil Sie zu einem Termin eingeladen sind.",
        "en": "You are receiving this email because you are invited to an appointment.",
    },
    "todo_assigned": {
        "de": "Sie erhalten diese E-Mail, weil Ihnen ein To-Do zugewiesen wurde.",
        "en": "You are receiving this email because a to-do was assigned to you.",
    },
    "todo_mentioned": {
        "de": "Sie erhalten diese E-Mail, weil Sie in einem To-Do erwähnt wurden.",
        "en": "You are receiving this email because you were mentioned on a to-do.",
    },
    "todo_due": {
        "de": "Sie erhalten diese E-Mail, weil ein To-Do, für das Sie zuständig sind, "
        "morgen fällig ist.",
        "en": "You are receiving this email because a to-do that you are responsible "
        "for is due tomorrow.",
    },
    "todo_board_added": {
        "de": "Sie erhalten diese E-Mail, weil Sie zu einem Board hinzugefügt wurden.",
        "en": "You are receiving this email because you were added to a board.",
    },
    "draft_reminder": {
        "de": "Sie erhalten diese E-Mail, weil Ihr Antrag noch nicht eingereicht ist.",
        "en": "You are receiving this email because your application is not submitted yet.",
    },
    "poll_started": {
        "de": "Sie erhalten diese E-Mail, weil Sie in diesem Gremium abstimmen dürfen.",
        "en": "You are receiving this email because you vote in this committee.",
    },
    "poll_reminder": {
        "de": "Sie erhalten diese E-Mail, weil Sie in diesem Gremium abstimmen dürfen "
        "und noch nicht geantwortet haben.",
        "en": "You are receiving this email because you vote in this committee and "
        "have not answered yet.",
    },
    "circular_open": {
        "de": "Sie erhalten diese E-Mail, weil Sie in diesem Gremium stimmberechtigt sind.",
        "en": "You are receiving this email because you have a vote in this committee.",
    },
    "circular_reminder": {
        "de": "Sie erhalten diese E-Mail, weil Sie in diesem Gremium stimmberechtigt sind "
        "und noch nicht abgestimmt haben.",
        "en": "You are receiving this email because you have a vote in this committee "
        "and have not cast a ballot yet.",
    },
    "mention": {
        "de": "Sie erhalten diese E-Mail, weil Sie erwähnt wurden.",
        "en": "You are receiving this email because you were mentioned.",
    },
    "generic": {
        "de": "Sie erhalten diese E-Mail von {name}.",
        "en": "You are receiving this email from {name}.",
    },
}

_SETTINGS_HINT = {
    "de": "Benachrichtigungen verwalten",
    "en": "Manage notifications",
}

_FONT = "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
_BODY_STYLE = f"margin:0;padding:0;background:{LIGHT.page};{_FONT}color:{LIGHT.text};"
_CARD_STYLE = (
    f"background:{LIGHT.card};border:1px solid {LIGHT.border};border-radius:8px;"
    f"padding:24px 24px 28px;color:{LIGHT.text};"
)
_HEAD_LINK_STYLE = f"font-size:18px;font-weight:700;color:{LIGHT.text};text-decoration:none;"
_FOOTER_STYLE = f"padding:16px 16px 0;font-size:12px;line-height:1.5;color:{LIGHT.muted};"
_FOOTER_LINK_STYLE = f"color:{LIGHT.muted};"


def reason_text(kind: str, lang: str, name: str) -> str:
    """Return the footer hint for a mail kind (fallback: generic hint, DE).

    ``name`` is the platform name of the branding; a hint that names the platform uses it.
    """
    table = _REASONS.get(kind, _REASONS["generic"])
    return pick_lang(table, lang).replace(_NAME, name)


#: URL in the escaped text; it ends before whitespace or "<". The linker splits off
#: trailing punctuation, so "https://x.de/y." stays clickable.
_URL_RE = re.compile(r"https?://[^\s<]+")
_TRAILING_PUNCT = ".,;:!?)]"
_LINK_STYLE = "word-break:break-all;"
#: The style attribute of a link that `_linkify` wrote. The frame adds the colour to
#: it, because the colour depends on the branding and on the place of the link.
_LINK_ATTR = f'style="{_LINK_STYLE}"'


def _coloured(linked: str, colour: str) -> str:
    """Give the links that `_linkify` wrote the inline colour ``colour``."""
    return linked.replace(_LINK_ATTR, f'style="{_LINK_STYLE}color:{colour};"')


def _linkify(escaped: str) -> str:
    """Turn URLs in escaped text into clickable `<a href>` anchors.

    Call this only AFTER `html.escape`. The function wraps already escaped text
    in anchors, so it adds no injection risk. An `&amp;` in an href decodes
    correctly.
    """

    def repl(match: re.Match[str]) -> str:
        found = match.group(0)
        url = found.rstrip(_TRAILING_PUNCT)
        tail = found[len(url) :]
        return f'<a href="{url}" style="{_LINK_STYLE}">{url}</a>{tail}'

    return _URL_RE.sub(repl, escaped)


def append_link_text(text: str, url: str, label: str) -> str:
    """Add the line ``label: url`` to a plain-text body.

    The function returns the text unchanged when it already contains the URL, for
    example through ``{{ link }}`` in the template.
    """
    if url in text:
        return text
    return f"{text.rstrip()}\n\n{label}: {url}\n"


def _action_button(url: str, label: str, accent: str) -> str:
    """Return the call-to-action button of the layout (escaped), filled with the accent."""
    style = (
        f"display:inline-block;background:{accent};color:{on_fill(accent)};font-weight:600;"
        "text-decoration:none;border-radius:6px;padding:10px 18px;"
    )
    return (
        '<p style="margin:20px 0 0;">'
        f'<a class="m-btn" href="{html.escape(url)}" style="{style}">{html.escape(label)}</a>'
        "</p>"
    )


def _absolute(url: str, base_url: str) -> str:
    """Return ``url`` as a full URL: a path of the platform gets the public base URL."""
    return base_url.rstrip("/") + url if url.startswith("/") else url


def _legal_links(brand: MailBrand, lang: str, base_url: str) -> tuple[tuple[str, str], ...]:
    """Return ``(label, full URL)`` of each legal link that has a label for ``lang``."""
    pairs = (
        (brand_text(link.label, lang), _absolute(link.url, base_url)) for link in brand.legal_links
    )
    return tuple((label, url) for label, url in pairs if label)


def append_brand_text(text: str, brand: MailBrand, lang: str, base_url: str) -> str:
    """End a plain-text body with the footer text and the legal links of the branding.

    The copyright line stays out of the plain-text part
    (§ F/collaboration/notifications/001001 to 001003).
    """
    footer = brand_text(brand.footer_text, lang)
    links = "\n".join(f"{label}: {url}" for label, url in _legal_links(brand, lang, base_url))
    blocks = [block for block in (footer, links) if block]
    return text.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n" if blocks else text


def _head(brand: MailBrand, base: str) -> str:
    """Return the head: the Wortmarke, or the Bildmarke and the name, or the name.

    The logo has the platform name as its alternative text, so the head still names the
    platform in a client that hides images (§ F/collaboration/notifications/000999).
    """
    name = html.escape(brand.name)
    logo = brand.logo
    if logo is None:
        return f'<a href="{base}" style="{_HEAD_LINK_STYLE}">{name}</a>'
    image = (
        f'<img class="m-logo" src="cid:{LOGO_CID}" alt="{name}" width="{logo.width}" '
        f'height="{logo.height}" style="display:inline-block;border:0;vertical-align:middle;">'
    )
    if logo.kind == "wordmark":
        return f'<a href="{base}" style="{_HEAD_LINK_STYLE}">{image}</a>'
    decorative = image.replace(f'alt="{name}"', 'alt=""')
    return (
        f'<a href="{base}" style="{_HEAD_LINK_STYLE}">{decorative}'
        f'<span style="vertical-align:middle;padding-left:10px;">{name}</span></a>'
    )


def _footer(brand: MailBrand, *, reason: str, lang: str, base: str, base_url: str) -> str:
    """Return the footer lines; the copyright line is the last one."""
    hint = html.escape(pick_lang(_SETTINGS_HINT, lang))
    footer_text = brand_text(brand.footer_text, lang)
    legal = " · ".join(
        f'<a href="{html.escape(url)}" style="{_FOOTER_LINK_STYLE}">{html.escape(label)}</a>'
        for label, url in _legal_links(brand, lang, base_url)
    )
    copyright_line = brand_text(brand.copyright, lang)
    lines = (
        f'<p style="margin:0 0 4px;">{html.escape(reason)}</p>',
        (
            '<p style="margin:0 0 4px;">'
            + _coloured(_linkify(html.escape(footer_text)), LIGHT.muted).replace("\n", "<br>")
            + "</p>"
            if footer_text
            else ""
        ),
        (
            '<p style="margin:0 0 4px;">'
            f'<a href="{base}/account/notifications" style="{_FOOTER_LINK_STYLE}">{hint}</a>'
            f' · <a href="{base}" style="{_FOOTER_LINK_STYLE}">{html.escape(brand.name)}</a></p>'
        ),
        f'<p style="margin:0 0 4px;">{legal}</p>' if legal else "",
        f'<p style="margin:0;">{html.escape(copyright_line)}</p>' if copyright_line else "",
    )
    return "\n            ".join(line for line in lines if line)


def _dark_style(accent: str) -> str:
    """Return the <style> block with the dark colours.

    ``!important`` lets a rule win over the inline light colour of the same element. The
    logo gets a light plate, because the branding has one logo and a logo for a light
    page can be unreadable on a dark one.
    """
    link = readable(accent, DARK.card)
    return f"""<style>
@media (prefers-color-scheme: dark) {{
  .m-page {{ background: {DARK.page} !important; color: {DARK.text} !important; }}
  .m-head a {{ color: {DARK.text} !important; }}
  .m-logo {{ background: #ffffff !important; border-radius: 6px; padding: 6px; }}
  .m-card {{ background: {DARK.card} !important; border-color: {DARK.border} !important;
    color: {DARK.text} !important; }}
  .m-card a {{ color: {link} !important; }}
  .m-card a.m-btn {{ color: {on_fill(accent)} !important; }}
  .m-card .m-muted {{ color: {DARK.muted} !important; }}
  .m-card .m-strong {{ color: {DARK.text} !important; }}
  .m-card .m-bubble {{ background: {DARK.border} !important; color: {DARK.text} !important; }}
  .m-foot, .m-foot a {{ color: {DARK.muted} !important; }}
}}
</style>"""


def text_to_html(text: str) -> str:
    """Convert a plain-text body to simple HTML.

    The result is escaped. It keeps the paragraphs and the line breaks and
    turns every URL into a clickable link.
    """
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    rendered = [
        '<p style="margin:0 0 1em;">'
        + _linkify(html.escape(p.strip())).replace("\n", "<br>")
        + "</p>"
        for p in paragraphs
    ]
    return "\n".join(rendered)


def render_layout(
    *,
    content_html: str,
    title: str,
    brand: MailBrand,
    base_url: str,
    reason: str,
    lang: str = "de",
    action_url: str | None = None,
    action_label: str | None = None,
) -> str:
    """Wrap the inner content in the branded mail layout (full document).

    This function escapes every value except `content_html`. The caller MUST
    pass safe HTML there: an autoescaped Jinja render or the output of
    `text_to_html`.

    `action_url` adds a button to the element of the mail below the content. The
    layout omits the button when the content already links the URL.

    The links of the content take the accent colour of the branding, darkened until it
    has 4.5:1 on the card (§ F/collaboration/notifications/001000). A link that
    `text_to_html` wrote gets the colour inline, and a link of a template HTML gets it
    from the <style> rule of the card.
    """
    esc_title = html.escape(title)
    base = html.escape(base_url.rstrip("/"))
    link_colour = readable(brand.accent, LIGHT.card)
    content = _coloured(content_html, link_colour)
    with_button = (
        content + "\n" + _action_button(action_url, action_label, brand.accent)
        if action_url and action_label and html.escape(action_url) not in content_html
        else content
    )
    table_open = (
        '<table class="m-page" role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" style="background:{LIGHT.page};padding:24px 0;">'
    )
    inner_open = (
        '<table role="presentation" width="600" cellpadding="0" '
        'cellspacing="0" style="max-width:600px;width:100%;">'
    )
    return f"""<!DOCTYPE html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{esc_title}</title>
<style>.m-card a {{ color: {link_colour}; }}</style>
{_dark_style(brand.accent)}
</head>
<body class="m-page" style="{_BODY_STYLE}">
  {table_open}
    <tr><td align="center">
      {inner_open}
        <tr>
          <td class="m-head" style="padding:0 16px 12px;">
            {_head(brand, base)}
          </td>
        </tr>
        <tr>
          <td class="m-card" style="{_CARD_STYLE}">
            <h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;">
              {esc_title}
            </h1>
            <div style="font-size:15px;line-height:1.55;">
{with_button}
            </div>
          </td>
        </tr>
        <tr>
          <td class="m-foot" style="{_FOOTER_STYLE}">
            {_footer(brand, reason=reason, lang=lang, base=base, base_url=base_url)}
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
