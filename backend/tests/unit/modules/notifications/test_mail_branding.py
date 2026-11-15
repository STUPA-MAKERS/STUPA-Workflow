"""Tests of the branding in mails: name, logo, accent, footer and the dark colours."""

from __future__ import annotations

import base64
import io
import re
import uuid
from typing import Any, cast

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.brand import (
    LOGO_CID,
    MailBrand,
    MailLegalLink,
    MailLogo,
    load_mail_brand,
    mail_brand,
)
from app.modules.notifications.colours import (
    AA,
    DARK,
    DEFAULT_ACCENT,
    LIGHT,
    contrast,
    normalize_accent,
    on_fill,
    readable,
)
from app.modules.notifications.compose import branded_mail
from app.modules.notifications.layout import append_brand_text, reason_text, render_layout
from app.modules.notifications.links import meeting_link
from app.modules.notifications.mail import MailInline, MailMessage, build_email_message
from app.modules.notifications.service import NotificationService
from app.modules.site_config.branding import Branding
from app.modules.site_config.models import SiteConfigVersion
from app.settings import load_settings
from tests._support.notifications_fakes import FakeQueue, FakeSession
from tests.unit.conftest import MailBranding

SETTINGS = load_settings(public_base_url="https://antrag.example.org")
ACCENTS = (DEFAULT_ACCENT, "#ffee00", "#101010", "#ff0000", "#0b6e4f", "#ffffff")


def _image(width: int, height: int, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "#336699").save(buffer, format=fmt)
    return buffer.getvalue()


def _asset(data: bytes, mime: str = "image/png") -> dict[str, Any]:
    url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    return {"url": url, "filename": "logo", "mime": mime, "size": len(data)}


def _branding(**fields: Any) -> Branding:
    return Branding.model_validate(fields)


def _layout(brand: MailBrand, lang: str = "de", content: str = "<p>Inhalt</p>") -> str:
    return render_layout(
        content_html=content,
        title="Titel",
        brand=brand,
        base_url="https://antrag.example.org/",
        reason="Grund",
        lang=lang,
        action_url="https://antrag.example.org/a",
        action_label="Öffnen",
    )


def _foot(html: str) -> str:
    return html.split('class="m-foot"', 1)[1]


# --- 000998: the name -----------------------------------------------------------------


def test_the_mail_names_the_platform_by_the_app_name() -> None:
    """§ F/collaboration/notifications/000998: head, footer and sender use the app name."""
    brand = mail_brand(_branding(appName="  STUPA  Portal "), SETTINGS)
    assert brand.name == "STUPA Portal"
    mail = branded_mail(
        brand=brand,
        settings=SETTINGS,
        to=("a@x.de",),
        subject="S",
        text="Hallo",
        reason="generic",
        lang="de",
        idempotency_key="k",
    )
    assert mail.from_name == "STUPA Portal"
    html = mail.html or ""
    head = html.split('class="m-head"', 1)[1].split("</td>", 1)[0]
    assert ">STUPA Portal</a>" in head
    assert "Sie erhalten diese E-Mail von STUPA Portal." in _foot(html)
    assert ">STUPA Portal</a>" in _foot(html)


def test_an_empty_app_name_gives_the_sender_name_of_the_server() -> None:
    """§ F/collaboration/notifications/000998: the fallback is ``MAIL_FROM_NAME``."""
    settings = load_settings(mail_from_name="Server-Name")
    assert mail_brand(Branding(), settings).name == "Server-Name"


def test_no_footer_reason_holds_a_fixed_platform_name() -> None:
    """§ F/collaboration/notifications/000998: a built-in text has no fixed name."""
    assert "Portal" in reason_text("application_captured", "de", "Portal")
    assert "Portal" in reason_text("application_captured", "en", "Portal")
    assert "Antragsplattform" not in reason_text("generic", "de", "Portal")
    assert "application platform" not in reason_text("generic", "en", "Portal")


async def test_the_access_link_subject_names_the_platform(mail_branding: MailBranding) -> None:
    """§ F/collaboration/notifications/000998: ``platformName`` reaches the builtin text."""
    mail_branding.active = _branding(appName="STUPA Portal")
    queue = FakeQueue()
    service = NotificationService(
        cast(AsyncSession, FakeSession(scalars=[[]])), queue=queue, settings=SETTINGS
    )
    await service.send_magic_link(email="a@x.de", link="https://l/#t=1", lang="de")
    assert queue.messages[0].subject == "Ihr Zugangslink für STUPA Portal"
    assert queue.messages[0].from_name == "STUPA Portal"


async def test_a_db_template_can_use_the_platform_name(mail_branding: MailBranding) -> None:
    """§ F/collaboration/notifications/000998: a template renders ``{{ platformName }}``."""
    mail_branding.active = _branding(appName="STUPA Portal")
    service = NotificationService(cast(AsyncSession, FakeSession()), settings=SETTINGS)
    assert await service.render_context({"link": "x"}) == {
        "platformName": "STUPA Portal",
        "link": "x",
    }
    assert await service.render_context({"platformName": "Eigen"}) == {"platformName": "Eigen"}


def test_the_sender_name_is_quoted_and_encoded() -> None:
    """§ F/collaboration/notifications/000998: a name with a comma or an umlaut is safe."""
    msg = MailMessage(to=("a@x.de",), subject="S", text="b", from_name='Büro, "StuPa"\nX')
    sender = build_email_message(msg, SETTINGS)["From"]
    assert sender.addresses[0].display_name == 'Büro, "StuPa" X'
    assert sender.addresses[0].addr_spec == SETTINGS.mail_from


@pytest.mark.real_branding
async def test_the_brand_comes_from_the_active_site_config() -> None:
    """§ F/collaboration/notifications/000998: the read uses the active branding row."""
    row = SiteConfigVersion(branding={"appName": "Aus der DB"}, active=True)
    with_row = cast(AsyncSession, FakeSession(scalars=[[row]]))
    assert (await load_mail_brand(with_row, SETTINGS)).name == "Aus der DB"
    without_row = cast(AsyncSession, FakeSession(scalars=[[]]))
    assert (await load_mail_brand(without_row, SETTINGS)).name == SETTINGS.mail_from_name


async def test_the_service_reads_the_brand_once(mail_branding: MailBranding) -> None:
    mail_branding.active = _branding(appName="Eins")
    service = NotificationService(cast(AsyncSession, FakeSession()), settings=SETTINGS)
    first = await service.brand()
    mail_branding.active = _branding(appName="Zwei")
    assert await service.brand() is first


# --- 000999: the logo -----------------------------------------------------------------


def test_the_head_shows_the_wordmark_as_an_inline_png() -> None:
    """§ F/collaboration/notifications/000999: the Wortmarke replaces the name."""
    branding = _branding(
        appName="Portal <1>",
        logos={
            "wordmark": _asset(_image(1200, 300, "WEBP"), "image/webp"),
            "imagemark": _asset(_image(64, 64)),
        },
    )
    brand = mail_brand(branding, SETTINGS)
    logo = brand.logo
    assert logo is not None and logo.kind == "wordmark"
    assert logo.png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(logo.png)) as png:
        assert png.height <= 120 and png.width <= 720
    assert (logo.width, logo.height) == (160, 40)
    mail = branded_mail(
        brand=brand,
        settings=SETTINGS,
        to=("a@x.de",),
        subject="S",
        text="Hallo",
        reason="generic",
        lang="de",
        idempotency_key="k",
    )
    assert mail.inline == (MailInline(cid=LOGO_CID, mime="image/png", content=logo.png),)
    html = mail.html or ""
    head = html.split('class="m-head"', 1)[1].split("</td>", 1)[0]
    assert f'src="cid:{LOGO_CID}"' in head
    assert 'alt="Portal &lt;1&gt;"' in head
    assert 'height="40"' in head
    assert "<span" not in head
    assert "cid:" not in mail.text


def test_the_head_shows_the_imagemark_beside_the_name() -> None:
    """§ F/collaboration/notifications/000999: without a Wortmarke, Bildmarke and name."""
    brand = mail_brand(
        _branding(appName="Portal", logos={"imagemark": _asset(_image(32, 32))}), SETTINGS
    )
    assert brand.logo is not None and brand.logo.kind == "imagemark"
    assert (brand.logo.width, brand.logo.height) == (32, 32)
    head = _layout(brand).split('class="m-head"', 1)[1].split("</td>", 1)[0]
    assert f'src="cid:{LOGO_CID}"' in head and 'alt=""' in head
    assert ">Portal</span>" in head


def test_a_url_logo_and_a_broken_logo_count_as_no_logo() -> None:
    """§ F/collaboration/notifications/000999: only inline image bytes give a logo."""
    url_logo = {"url": "https://cdn.example.org/l.png", "filename": "l", "mime": "image/png"}
    by_url = mail_brand(_branding(logos={"wordmark": {**url_logo, "size": 10}}), SETTINGS)
    assert by_url.logo is None
    broken = b"\x89PNG\r\n\x1a\n" + b"no image data"
    by_bytes = mail_brand(_branding(logos={"wordmark": _asset(broken)}), SETTINGS)
    assert by_bytes.logo is None
    mail = branded_mail(
        brand=by_url,
        settings=SETTINGS,
        to=("a@x.de",),
        subject="S",
        text="Hallo",
        reason="generic",
        lang="de",
        idempotency_key="k",
    )
    assert mail.inline == ()
    assert "<img" not in (mail.html or "")


def test_the_html_loads_no_remote_resource() -> None:
    """§ F/collaboration/notifications/000999: no ``src`` and no stylesheet is remote."""
    brand = MailBrand(name="P", logo=MailLogo(png=b"x", kind="wordmark", width=80, height=40))
    html = _layout(brand)
    assert re.findall(r'src="([^"]*)"', html) == [f"cid:{LOGO_CID}"]
    assert "<link" not in html and "url(" not in html and "@import" not in html


def test_the_logo_is_a_related_part_of_the_html() -> None:
    """§ F/collaboration/notifications/000999: the mail carries the logo as an inline part."""
    msg = MailMessage(
        to=("a@x.de",),
        subject="S",
        text="b",
        html=f'<img src="cid:{LOGO_CID}">',
        inline=(MailInline(cid=LOGO_CID, mime="image/png", content=_image(4, 4)),),
    )
    assert MailMessage.from_payload(msg.to_payload()) == msg
    email = build_email_message(msg, SETTINGS)
    image = next(part for part in email.walk() if part.get_content_type() == "image/png")
    assert image["Content-ID"] == f"<{LOGO_CID}>"
    assert image.get_content_disposition() == "inline"
    related = next(part for part in email.walk() if part.get_content_type() == "multipart/related")
    assert next(iter(related.iter_parts())).get_content_type() == "text/html"


def test_an_old_queue_payload_has_no_inline_part() -> None:
    payload = MailMessage(to=("a@x.de",), subject="S", text="b").to_payload()
    old = {key: value for key, value in payload.items() if key != "inline"}
    assert MailMessage.from_payload(old).inline == ()


# --- 001000: the accent ---------------------------------------------------------------


def test_the_accent_of_the_branding_colours_button_and_links() -> None:
    """§ F/collaboration/notifications/001000: the button fill is the accent."""
    brand = mail_brand(_branding(accentColor="#0B6E4F"), SETTINGS)
    assert brand.accent == "#0b6e4f"
    html = _layout(
        brand, content='<p><a href="https://x.de" style="word-break:break-all;">x</a></p>'
    )
    assert "background:#0b6e4f;color:#ffffff;" in html
    assert 'style="word-break:break-all;color:#0b6e4f;"' in html
    assert ".m-card a { color: #0b6e4f; }" in html


def test_without_an_accent_the_mail_uses_the_built_in_one() -> None:
    """§ F/collaboration/notifications/001000: the fallback is the design-system accent."""
    assert mail_brand(Branding(), SETTINGS).accent == "#72a384"
    assert normalize_accent("red") == DEFAULT_ACCENT
    assert normalize_accent(None) == DEFAULT_ACCENT


@pytest.mark.parametrize("accent", ACCENTS)
def test_every_accent_keeps_the_contrast(accent: str) -> None:
    """§ F/collaboration/notifications/001000: 4.5:1 for the links and the button text."""
    assert contrast(readable(accent, LIGHT.card), LIGHT.card) >= AA
    assert contrast(readable(accent, DARK.card), DARK.card) >= AA
    assert contrast(on_fill(accent), accent) >= AA
    html = _layout(MailBrand(name="P", accent=accent))
    assert f"color:{on_fill(accent)};" in html
    assert f".m-card a {{ color: {readable(accent, DARK.card)} !important; }}" in html


# --- 001001: the footer text ----------------------------------------------------------


def test_the_footer_shows_the_footer_text_in_the_language_of_the_mail() -> None:
    """§ F/collaboration/notifications/001001: escaped, with line breaks and links."""
    brand = mail_brand(
        _branding(
            freetexts={
                "emailFooter": {
                    "de": "Zeile <b>1</b>\nFragen: https://hilfe.example.org/x.",
                    "en": "English footer",
                    "fr": "  ",
                }
            }
        ),
        SETTINGS,
    )
    german = _foot(_layout(brand, "de"))
    assert "Zeile &lt;b&gt;1&lt;/b&gt;<br>Fragen:" in german
    assert '<a href="https://hilfe.example.org/x"' in german
    assert f"color:{LIGHT.muted};" in german
    assert "English footer" in _foot(_layout(brand, "en"))
    assert "English footer" in _foot(_layout(brand, "fr"))
    only_german = MailBrand(name="P", footer_text={"de": "Nur deutsch"})
    assert "Nur deutsch" in _foot(_layout(only_german, "en"))


def test_the_plain_text_ends_with_the_footer_text() -> None:
    """§ F/collaboration/notifications/001001: the text part carries the same text."""
    brand = MailBrand(name="P", footer_text={"de": "Automatische Nachricht."})
    link = meeting_link(SETTINGS, uuid.uuid4())
    mail = branded_mail(
        brand=brand,
        settings=SETTINGS,
        to=("a@x.de",),
        subject="S",
        text="Hallo\n",
        reason="meeting",
        lang="de",
        idempotency_key="k",
        link=link,
    )
    assert mail.text == f"Hallo\n\n{link.label('de')}: {link.url}\n\nAutomatische Nachricht.\n"


def test_a_mail_without_a_footer_text_has_no_such_line() -> None:
    """§ F/collaboration/notifications/001001: no text, no line."""
    brand = MailBrand(name="P")
    assert append_brand_text("Hallo\n", brand, "de", "https://x.de") == "Hallo\n"
    assert _foot(_layout(brand)).count("<p") == 2


# --- 001002: the copyright line -------------------------------------------------------


def test_the_copyright_line_is_the_last_line_of_the_footer() -> None:
    """§ F/collaboration/notifications/001002: last line, language of the mail, HTML only."""
    brand = mail_brand(
        _branding(
            copyright={"de": "© StuPa <Reutlingen>", "en": "© Student Parliament"},
            freetexts={"emailFooter": {"de": "Fuß"}},
            legalLinks=[{"label": {"de": "Impressum"}, "url": "/imprint"}],
        ),
        SETTINGS,
    )
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", _foot(_layout(brand, "de")), re.S)
    assert paragraphs[-1] == "© StuPa &lt;Reutlingen&gt;"
    assert "© Student Parliament" in _foot(_layout(brand, "en"))
    assert "©" not in append_brand_text("Hallo", brand, "de", "https://x.de")
    assert "©" not in _foot(_layout(MailBrand(name="P")))


# --- 001003: the legal links ----------------------------------------------------------


def test_the_footer_shows_the_legal_links_in_one_line() -> None:
    """§ F/collaboration/notifications/001003: order, labels, full URLs, bad links left out."""
    brand = mail_brand(
        _branding(
            legalLinks=[
                {"label": {"de": "Impressum", "en": "Imprint"}, "url": "/imprint"},
                {
                    "label": {"de": "Daten & Schutz"},
                    "url": "https://uni.example.org/privacy?a=1&b=2",
                },
                {"label": {"de": " "}, "url": "/no-label"},
                {"label": {"de": "Mail"}, "url": "mailto:stupa@example.org"},
                {"label": {"de": "Fremd"}, "url": "//evil.example.org/x"},
            ]
        ),
        SETTINGS,
    )
    assert brand.legal_links == (
        MailLegalLink(label={"de": "Impressum", "en": "Imprint"}, url="/imprint"),
        MailLegalLink(
            label={"de": "Daten & Schutz"}, url="https://uni.example.org/privacy?a=1&b=2"
        ),
    )
    foot = _foot(_layout(brand, "en"))
    line = next(p for p in re.findall(r"<p[^>]*>(.*?)</p>", foot, re.S) if "Imprint" in p)
    assert line.index("Imprint") < line.index("Daten &amp; Schutz")
    assert 'href="https://antrag.example.org/imprint"' in line
    assert 'href="https://uni.example.org/privacy?a=1&amp;b=2"' in line
    assert "no-label" not in foot and "mailto:" not in foot and "evil" not in foot
    text = append_brand_text("Hallo\n", brand, "de", "https://antrag.example.org/")
    assert text == (
        "Hallo\n\nImpressum: https://antrag.example.org/imprint\n"
        "Daten & Schutz: https://uni.example.org/privacy?a=1&b=2\n"
    )


def test_the_plain_text_has_the_footer_text_before_the_legal_links() -> None:
    brand = MailBrand(
        name="P",
        footer_text={"de": "Fuß"},
        legal_links=(MailLegalLink(label={"de": "Impressum"}, url="https://x.de/i"),),
    )
    assert append_brand_text("Hallo", brand, "de", "https://x.de") == (
        "Hallo\n\nFuß\n\nImpressum: https://x.de/i\n"
    )


# --- 001004: light and dark -----------------------------------------------------------


def test_both_colour_sets_keep_the_contrast() -> None:
    """§ F/collaboration/notifications/001004: text and muted text have 4.5:1 in each set."""
    for colours in (LIGHT, DARK):
        assert contrast(colours.text, colours.card) >= AA
        assert contrast(colours.text, colours.page) >= AA
        assert contrast(colours.muted, colours.page) >= AA
        assert contrast(colours.muted, colours.card) >= AA
    assert contrast(DARK.text, DARK.border) >= AA


def test_the_dark_set_applies_only_on_request_of_the_client() -> None:
    """§ F/collaboration/notifications/001004: light inline, dark behind the media query."""
    brand = MailBrand(name="P", logo=MailLogo(png=b"x", kind="wordmark", width=80, height=40))
    html = _layout(brand)
    assert '<meta name="color-scheme" content="light dark">' in html
    before, dark = html.split("@media (prefers-color-scheme: dark)", 1)
    assert DARK.card not in before and DARK.page not in before
    rules = dark.split("</style>", 1)[0]
    assert f".m-card {{ background: {DARK.card} !important;" in rules
    assert (
        f".m-page {{ background: {DARK.page} !important; color: {DARK.text} !important; }}" in rules
    )
    assert f".m-foot, .m-foot a {{ color: {DARK.muted} !important; }}" in rules
    assert ".m-logo { background: #ffffff !important;" in rules
    body = html.split("</head>", 1)[1]
    assert f"background:{LIGHT.card};" in body and f"background:{LIGHT.page};" in body
    assert DARK.card not in body
