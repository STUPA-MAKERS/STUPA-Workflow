"""Branded HTML-Mail-Layout (#4): ein Rahmen in Code, Inhalt aus Templates.

Jede ausgehende Mail wird in dasselbe Layout gehüllt (Header mit Plattform-Name,
Inhalts-Karte, Footer mit Auslöser-Hinweis + Link zu den Benachrichtigungs-
Einstellungen). DB-Templates liefern nur den **inneren** Inhalt — liegt kein
HTML-Body vor, wird der Text-Body escaped + umgebrochen übernommen, sodass auch
text-only Templates eine ansehnliche HTML-Alternative bekommen.

Inline-CSS (Mail-Clients ignorieren <style> teils), keine externen Ressourcen.
"""

from __future__ import annotations

import html
import re

# Auslöser-Hinweis im Footer („Sie erhalten diese E-Mail, weil …") je Mail-Art.
_REASONS: dict[str, dict[str, str]] = {
    "magic_link": {
        "de": "Sie erhalten diese E-Mail, weil für Ihre Adresse ein "
        "Zugangslink angefordert wurde.",
        "en": "You are receiving this email because an access link was "
        "requested for your address.",
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
    "deadline": {
        "de": "Sie erhalten diese E-Mail, weil eine Frist zu einem Antrag "
        "näher rückt, der Sie betrifft.",
        "en": "You are receiving this email because a deadline on an "
        "application that concerns you is approaching.",
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
    "vote": {
        "de": "Sie erhalten diese E-Mail, weil eine Abstimmung geöffnet "
        "oder geschlossen wurde, die Sie betrifft.",
        "en": "You are receiving this email because a vote that concerns "
        "you was opened or closed.",
    },
    "role_change": {
        "de": "Sie erhalten diese E-Mail, weil sich Ihre Rollen auf der "
        "Plattform geändert haben.",
        "en": "You are receiving this email because your roles on the "
        "platform changed.",
    },
    "delegation": {
        "de": "Sie erhalten diese E-Mail, weil eine Stimm-Delegation "
        "erteilt oder widerrufen wurde, die Sie betrifft.",
        "en": "You are receiving this email because a vote delegation that "
        "concerns you was granted or revoked.",
    },
    "generic": {
        "de": "Sie erhalten diese E-Mail von der Antragsplattform.",
        "en": "You are receiving this email from the application platform.",
    },
}

_SETTINGS_HINT = {
    "de": "Benachrichtigungen verwalten",
    "en": "Manage notifications",
}

_BODY_STYLE = (
    "margin:0;padding:0;background:#f2f4f8;"
    "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    "color:#1f2933;"
)
_CARD_STYLE = (
    "background:#ffffff;border:1px solid #e0e4ea;border-radius:8px;"
    "padding:24px 24px 28px;"
)
_HEAD_LINK_STYLE = (
    "font-size:18px;font-weight:700;color:#1f2933;text-decoration:none;"
)
_FOOTER_STYLE = "padding:16px 16px 0;font-size:12px;line-height:1.5;color:#6b7686;"


def reason_text(kind: str, lang: str) -> str:
    """Footer-Hinweis für eine Mail-Art (Fallback: generischer Hinweis, DE)."""
    table = _REASONS.get(kind, _REASONS["generic"])
    return table.get(lang, table["de"])


# URLs im (bereits escapten) Text — endet vor Whitespace/<; angehängte
# Satzzeichen werden unten abgetrennt, damit »https://x.de/y.« klickbar bleibt.
_URL_RE = re.compile(r"https?://[^\s<]+")
_TRAILING_PUNCT = ".,;:!?)]"
_LINK_STYLE = "color:#0b6e4f;word-break:break-all;"


def _linkify(escaped: str) -> str:
    """URLs im escapten Text in klickbare ``<a href>`` verwandeln.

    Läuft NACH ``html.escape`` — ``&`` in Query-Strings steht als ``&amp;`` im
    ``href``, was beim Klick korrekt dekodiert wird. Kein neues Injection-
    Risiko: es wird nur bereits escapter Text in Anker gehüllt."""

    def repl(match: re.Match[str]) -> str:
        url = match.group(0)
        tail = ""
        while url and url[-1] in _TRAILING_PUNCT:
            tail = url[-1] + tail
            url = url[:-1]
        return f'<a href="{url}" style="{_LINK_STYLE}">{url}</a>{tail}'

    return _URL_RE.sub(repl, escaped)


def text_to_html(text: str) -> str:
    """Plain-Text-Body → einfacher HTML-Inhalt (escaped, Absätze + Umbrüche,
    URLs als klickbare Links)."""
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
    site_name: str,
    base_url: str,
    reason: str,
    lang: str = "de",
) -> str:
    """Inneren Inhalt ins gebrandete Mail-Layout hüllen (vollständiges Dokument).

    ``content_html`` MUSS bereits sicher sein (autoescaped Jinja-Render bzw.
    :func:`text_to_html`); alle übrigen Werte werden hier escaped."""
    esc_title = html.escape(title)
    esc_site = html.escape(site_name)
    esc_reason = html.escape(reason)
    base = html.escape(base_url.rstrip("/"))
    settings_url = f"{base}/account/notifications"
    hint = html.escape(_SETTINGS_HINT.get(lang, _SETTINGS_HINT["de"]))
    table_open = (
        '<table role="presentation" width="100%" cellpadding="0" '
        'cellspacing="0" style="background:#f2f4f8;padding:24px 0;">'
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
<title>{esc_title}</title>
</head>
<body style="{_BODY_STYLE}">
  {table_open}
    <tr><td align="center">
      {inner_open}
        <tr>
          <td style="padding:0 16px 12px;">
            <a href="{base}" style="{_HEAD_LINK_STYLE}">{esc_site}</a>
          </td>
        </tr>
        <tr>
          <td style="{_CARD_STYLE}">
            <h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;">
              {esc_title}
            </h1>
            <div style="font-size:15px;line-height:1.55;">
{content_html}
            </div>
          </td>
        </tr>
        <tr>
          <td style="{_FOOTER_STYLE}">
            <p style="margin:0 0 4px;">{esc_reason}</p>
            <p style="margin:0;">
              <a href="{settings_url}" style="color:#6b7686;">{hint}</a>
              · <a href="{base}" style="color:#6b7686;">{esc_site}</a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
