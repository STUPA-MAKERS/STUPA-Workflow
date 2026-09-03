"""Server-rendered HTML for a public share link.

This exists because the platform is an SPA with no SSR, and Matrix, WhatsApp and Signal
build their link previews by fetching the URL server-side and reading OpenGraph tags out
of the returned HTML. A bot that receives the SPA shell sees an empty page and shows a
bare URL. So the share route cannot be an Angular route: the server has to answer with
real HTML.

The page is written by hand rather than through a template engine. It is one page, it must
be self-contained (a preview bot follows no stylesheet), and every value on it is escaped
at exactly one place, which is easier to check than a template's escaping rules.

**The preview carries the title and nothing else.** That text lands permanently on a chat
server we do not control and cannot delete from. The amount, the state, the cost breakdown
and the applicant all stay out of the meta tags, on purpose — a preview that says
"€4,200, rejected" has published a decision to everyone in the room before anyone opened
the link.
"""

from __future__ import annotations

import base64
import hashlib
from html import escape
from urllib.parse import urlsplit

from app.modules.applications.share import (
    Position,
    PositionBlock,
    PublicApplication,
    format_money,
    to_decimal,
)

#: The preview description. Deliberately says nothing about the application: whatever
#: goes here is public the moment the link is pasted.
_PREVIEW_DESCRIPTION = {"de": "Geteilter Antrag", "en": "Shared application"}

#: Every reader-facing string on the page. The route already knows the language of the
#: application, so a German page around English content (or the reverse) would be a
#: choice rather than an oversight.
_TEXT: dict[str, dict[str, str]] = {
    "de": {
        "gremium": "Gremium",
        "type": "Art",
        "status": "Status",
        "amount": "Betrag",
        "data": "Antragsdaten",
        "preferred": "Bevorzugt",
        "no_offers": "Ohne Vergleichsangebote",
        "total": "Gesamtbetrag",
        "open": "Im Portal öffnen",
        "open_hint": "Mitglieder mit Zugang sehen dort den vollständigen Antrag.",
        "footer": "schreibgeschützte Ansicht ohne Kommentare und Änderungsverlauf.",
    },
    "en": {
        "gremium": "Committee",
        "type": "Type",
        "status": "Status",
        "amount": "Amount",
        "data": "Application data",
        "preferred": "Preferred",
        "no_offers": "Without comparison offers",
        "total": "Total amount",
        "open": "Open in the portal",
        "open_hint": "Members with access see the full application there.",
        "footer": "read-only view without comments and change history.",
    },
}


#: The stylesheet, as a module constant rather than part of the template: the CSP
#: below hashes exactly these bytes.
#:
#: The colours are the product's own (British Racing Green plus the bronze accent from
#: the ui-kit tokens), written out rather than imported: this page ships without the SPA's
#: stylesheet and a preview bot follows no link. They are the same for every instance —
#: the branding a deployment really configures is its name and its logo, and both reach
#: the page through `render_share_page`.
_CSS = """:root { color-scheme: light dark;
  --fg: #141815; --muted: #666c67; --bg: #f7f8f7; --line: #e0e3e0; --card: #ffffff;
  --brand: #004225; --on-brand: #ffffff; --accent: #8c6820; --sunken: #eef0ee; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #eef0ee; --muted: #9aa19c; --bg: #141815; --line: #3a3f3b;
    --card: #1b1f1c; --brand: #72a384; --on-brand: #0c0f0d; --accent: #c8a25a;
    --sunken: #232724; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 46rem; margin-inline: auto; padding: 0 1rem 3rem; }
.brand { background: var(--brand); color: var(--on-brand); padding: 1rem;
  margin-bottom: 2rem; }
.brand__in { max-width: 46rem; margin-inline: auto; display: flex; align-items: center;
  gap: 0.75rem; }
.brand__logo { height: 2rem; width: auto; max-width: 12rem; object-fit: contain; }
.brand__name { font-weight: 600; letter-spacing: 0.01em; }
h1 { font-size: 1.75rem; line-height: 1.2; margin: 0 0 0.75rem; letter-spacing: -0.01em; }
h2 { font-size: 1rem; margin: 0 0 0.75rem; color: var(--muted); font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em; }
.meta { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0 0 2rem; padding: 0;
  list-style: none; }
.meta li { background: var(--sunken); border: 1px solid var(--line); border-radius: 999px;
  padding: 0.2rem 0.7rem; font-size: 0.875rem; }
.meta b { font-weight: 600; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 14px;
  padding: 1.25rem 1.5rem; margin-bottom: 1.5rem; }
.row { display: grid; grid-template-columns: 13rem 1fr; gap: 0.5rem 1.5rem;
  padding: 0.6rem 0; border-bottom: 1px solid var(--line); }
.row:last-child { border-bottom: 0; padding-bottom: 0; }
.row:first-of-type { padding-top: 0; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; white-space: pre-line; }
.pos { border: 1px solid var(--line); border-radius: 10px; padding: 0.9rem 1rem;
  margin-bottom: 0.75rem; }
.pos__head { display: flex; justify-content: space-between; align-items: baseline;
  gap: 1rem; font-weight: 600; }
.pos__val { white-space: nowrap; }
.offers { list-style: none; margin: 0.6rem 0 0; padding: 0; display: flex;
  flex-direction: column; gap: 0.3rem; }
/* A vendor name is as long as the vendor made it. Without the wrap and the shrinkable
   label the offer value pushed the whole page wider than a phone screen. */
.offer { display: flex; align-items: baseline; gap: 0.6rem; font-size: 0.9375rem;
  color: var(--muted); flex-wrap: wrap; }
.offer--pref { color: var(--fg); }
.offer > span:first-child { min-width: 0; overflow-wrap: anywhere; }
.offer__val { margin-left: auto; white-space: nowrap; }
.tag { font-size: 0.75rem; border-radius: 999px; padding: 0.05rem 0.5rem;
  border: 1px solid currentColor; white-space: nowrap; }
.tag--pref { color: var(--brand); }
.tag--none { color: var(--accent); }
.pos__note { margin: 0.6rem 0 0; font-size: 0.9375rem; color: var(--muted); }
.total { display: flex; justify-content: space-between; gap: 1rem; font-weight: 600;
  border-top: 2px solid var(--line); padding-top: 0.75rem; margin-top: 0.25rem; }
.cta { display: block; text-align: center; background: var(--brand);
  color: var(--on-brand); text-decoration: none; font-weight: 600;
  padding: 0.8rem 1.5rem; border-radius: 10px; }
.cta:hover { filter: brightness(1.12); }
.cta:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
.cta__hint { color: var(--muted); font-size: 0.875rem; text-align: center;
  margin: 0.6rem 0 0; }
footer { color: var(--muted); font-size: 0.875rem; margin-top: 2.5rem; }
@media (max-width: 34rem) {
  .row { grid-template-columns: 1fr; gap: 0.125rem; }
  h1 { font-size: 1.4rem; }
  .card { padding: 1rem; }
}
"""

#: The page carries its own policy, because the API-wide one forbids what it needs.
#:
#: `SecurityHeadersMiddleware` puts `default-src 'none'` on every response that does
#: not already carry a CSP. That blocks this page's own <style> and leaves it as raw
#: unstyled markup. A hash rather than 'unsafe-inline': the stylesheet is fixed at
#: import time, so nothing has to trust arbitrary inline CSS.
_STYLE_HASH = base64.b64encode(hashlib.sha256(_CSS.encode()).digest()).decode()

#: The policy for a page without a logo, which is also the narrowest one: no images at
#: all. `share_csp` widens `img-src` by exactly the one source a logo needs.
SHARE_CSP = (
    "default-src 'none'; "
    f"style-src 'sha256-{_STYLE_HASH}'; "
    "img-src 'none'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


def share_csp(logo_url: str | None) -> str:
    """The policy for one rendered page, naming where its logo may come from.

    `img-src https:` would allow every host on the internet to be contacted from a page
    an outsider opens. The page loads at most one image, so the policy names exactly that
    source and nothing wider.
    """
    source = _logo_source(logo_url)
    if source is None:
        return SHARE_CSP
    return SHARE_CSP.replace("img-src 'none'", f"img-src {source}")


def _logo_source(logo_url: str | None) -> str | None:
    """The CSP source for a logo, or `None` where it must not be loaded at all.

    Inline data and HTTPS only. A logo over plain `http:` would be mixed content, and any
    remote logo tells its host the IP address of everyone who opens the link — over
    `http:` it would do that in the clear as well, so that case is refused rather than
    degraded.
    """
    if not logo_url:
        return None
    raw = logo_url.strip()
    if raw.lower().startswith("data:"):
        return "data:"
    parts = urlsplit(raw)
    if parts.scheme == "https" and parts.netloc:
        return f"https://{parts.netloc}"
    return None


def render_share_page(
    view: PublicApplication,
    *,
    app_name: str,
    canonical_url: str,
    lang: str = "de",
    app_url: str | None = None,
    logo_url: str | None = None,
) -> str:
    """Return the complete HTML document for one shared application.

    `app_url` is the application inside the SPA. A reader who has an account should not
    have to search for what they were just sent; one without an account meets the login,
    which is the correct answer rather than a dead end.
    """
    text = _TEXT.get(lang, _TEXT["de"])
    title = escape(view.title)
    # The og:title is the ONE piece of the application that reaches a chat server.
    og_title = f"{title} — {escape(app_name)}"

    meta_bits = [
        (text["gremium"], view.gremium_name),
        (text["type"], view.type_name),
        (text["status"], view.state_label),
        (text["amount"], _amount(view, lang)),
    ]
    meta = "\n".join(
        f"    <li><b>{escape(k)}:</b> {escape(v)}</li>" for k, v in meta_bits if v
    )
    meta_block = f'  <ul class="meta">\n{meta}\n  </ul>' if meta else ""

    rows = "\n".join(
        f"      <div class='row'><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
        for label, value in view.fields
    )
    data_card = (
        f'  <h2>{escape(text["data"])}</h2>\n  <dl class="card">\n{rows}\n  </dl>'
        if rows
        else ""
    )

    blocks = "\n".join(_render_block(b, text) for b in view.positions)

    cta = ""
    if app_url:
        cta = (
            f'  <a class="cta" href="{escape(app_url)}">{escape(text["open"])}</a>\n'
            f'  <p class="cta__hint">{escape(text["open_hint"])}</p>'
        )

    logo = ""
    if _logo_source(logo_url) is not None and logo_url:
        logo = (
            f'<img class="brand__logo" src="{escape(logo_url.strip())}" '
            f'alt="{escape(app_name)}">'
        )

    description = _PREVIEW_DESCRIPTION.get(lang, _PREVIEW_DESCRIPTION["de"])

    return f"""<!doctype html>
<html lang="{escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{og_title}</title>
<link rel="canonical" href="{escape(canonical_url)}">
<link rel="icon" href="data:,">
<!-- A public page must not enter a search index. It is meant for whoever holds the URL,
     not for everyone who searches the applicant's name. -->
<meta name="robots" content="noindex, nofollow">
<meta property="og:type" content="article">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:url" content="{escape(canonical_url)}">
<meta property="og:site_name" content="{escape(app_name)}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{escape(description)}">
<style>{_CSS}</style>
</head>
<body>
<header class="brand">
  <div class="brand__in">{logo}<span class="brand__name">{escape(app_name)}</span></div>
</header>
<main>
  <h1>{title}</h1>
{meta_block}
{data_card}
{blocks}
{cta}
  <footer>
    <p>{escape(app_name)} — {escape(text["footer"])}</p>
  </footer>
</main>
</body>
</html>
"""


def _amount(view: PublicApplication, lang: str) -> str | None:
    """The headline amount, in the same money format as the breakdown below it.

    It used to be the stored decimal and the currency code joined with a space, so one
    page showed "1730.00 EUR" above "1.730,00 €" — the same number written two ways, which
    reads as two different numbers.
    """
    if not view.amount:
        return None
    num = to_decimal(view.amount)
    if num is None:
        return f"{view.amount} {view.currency}".strip()
    return format_money(num, view.currency or "EUR", lang)


def _render_block(block: PositionBlock, text: dict[str, str]) -> str:
    """One cost breakdown: every position, every comparison offer, and the total.

    The losing quotes are part of the answer rather than noise — without them a reader
    cannot check the claim that the cheapest offer was taken.
    """
    positions = "\n".join(_render_position(p, text) for p in block.positions)
    total = ""
    if block.total is not None:
        total = (
            f'    <p class="total"><span>{escape(text["total"])}</span>'
            f"<span>{escape(block.total)}</span></p>"
        )
    return (
        f"  <h2>{escape(block.label)}</h2>\n"
        f'  <section class="card">\n{positions}\n{total}\n  </section>'
    )


def _render_position(position: Position, text: dict[str, str]) -> str:
    """One position: its name, what it is worth, its quotes and any opt-out reason."""
    offers = "\n".join(
        f'        <li class="offer{" offer--pref" if o.preferred else ""}">'
        f"<span>{escape(o.label)}</span>"
        + (f'<span class="tag tag--pref">{escape(text["preferred"])}</span>' if o.preferred else "")
        + f'<span class="offer__val">{escape(o.value)}</span></li>'
        for o in position.offers
    )
    offer_list = f'      <ul class="offers">\n{offers}\n      </ul>' if offers else ""
    note = ""
    if position.no_offers_reason:
        note = (
            f'      <p class="pos__note"><span class="tag tag--none">'
            f'{escape(text["no_offers"])}</span> {escape(position.no_offers_reason)}</p>'
        )
    value = escape(position.value) if position.value else ""
    return (
        f'    <div class="pos">\n'
        f'      <p class="pos__head"><span>{escape(position.label)}</span>'
        f'<span class="pos__val">{value}</span></p>\n'
        f"{offer_list}\n{note}\n    </div>"
    )
