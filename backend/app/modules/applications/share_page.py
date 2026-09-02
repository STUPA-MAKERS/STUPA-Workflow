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
server we do not control and cannot delete from. The amount, the state and the applicant
all stay out of the meta tags, on purpose — a preview that says "€4,200, rejected" has
published a decision to everyone in the room before anyone opened the link.
"""

from __future__ import annotations

from html import escape

from app.modules.applications.share import PublicApplication

#: A preview description that says what the page is without describing the application.
#: Deliberately generic: whatever goes here is public the moment the link is pasted.
_PREVIEW_DESCRIPTION = "Antrag der Antragsplattform, öffentlich einsehbar."


def render_share_page(
    view: PublicApplication, *, app_name: str, canonical_url: str, lang: str = "de"
) -> str:
    """Return the complete HTML document for one shared application."""
    title = escape(view.title)
    # The og:title is the ONE piece of the application that reaches a chat server.
    og_title = f"{title} — {escape(app_name)}"

    rows = "\n".join(
        f"      <div class='row'><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
        for label, value in view.fields
    )
    meta_bits = [
        ("Gremium", view.gremium_name),
        ("Art", view.type_name),
        ("Status", view.state_label),
        (
            "Betrag",
            f"{view.amount} {view.currency}" if view.amount and view.currency else None,
        ),
    ]
    meta = "\n".join(
        f"      <div class='row'><dt>{escape(k)}</dt><dd>{escape(v)}</dd></div>"
        for k, v in meta_bits
        if v
    )

    return f"""<!doctype html>
<html lang="{escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{og_title}</title>
<link rel="canonical" href="{escape(canonical_url)}">
<!-- A public page must not enter a search index. It is meant for whoever holds the URL,
     not for everyone who searches the applicant's name. -->
<meta name="robots" content="noindex, nofollow">
<meta property="og:type" content="article">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{escape(_PREVIEW_DESCRIPTION)}">
<meta property="og:url" content="{escape(canonical_url)}">
<meta property="og:site_name" content="{escape(app_name)}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{escape(_PREVIEW_DESCRIPTION)}">
<style>
:root {{ color-scheme: light dark; --fg: #14261c; --muted: #5c6b63; --bg: #fbfcfb;
         --line: #dfe5e1; --card: #fff; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --fg: #e7ece9; --muted: #9aa8a1; --bg: #101613; --line: #2a332e; --card: #161d19; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
        font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width: 44rem; margin-inline: auto; }}
h1 {{ font-size: 1.6rem; line-height: 1.25; margin: 0 0 1.5rem; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px;
         padding: 1rem 1.25rem; margin-bottom: 1.25rem; }}
.row {{ display: grid; grid-template-columns: 12rem 1fr; gap: 0.5rem 1rem;
        padding: 0.5rem 0; border-bottom: 1px solid var(--line); }}
.row:last-child {{ border-bottom: 0; }}
dt {{ color: var(--muted); }}
dd {{ margin: 0; overflow-wrap: anywhere; }}
footer {{ color: var(--muted); font-size: 0.875rem; margin-top: 2rem; }}
@media (max-width: 34rem) {{ .row {{ grid-template-columns: 1fr; gap: 0.125rem; }} }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <dl class="card">
{meta}
  </dl>
  <dl class="card">
{rows}
  </dl>
  <footer>
    <p>{escape(app_name)} — schreibgeschützte Ansicht. Kommentare und Änderungsverlauf
       sind nicht Teil dieser Seite.</p>
  </footer>
</main>
</body>
</html>
"""
