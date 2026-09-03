"""Unit tests for public share links.

The point of these is the security surface, not the happy path. A share link is the one
route on the platform that answers without a principal, so what it refuses matters more
than what it renders.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.applications.models import ApplicationShare
from app.modules.applications.share import (
    DEFAULT_TTL_DAYS,
    MAX_TTL_DAYS,
    PublicApplication,
    ShareService,
    build_public_view,
    clamp_ttl,
    new_token,
)
from app.modules.applications.share_page import SHARE_CSP, render_share_page, share_csp
from app.modules.auth import tokens
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError

PEPPER = "pepper-for-tests-only"
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


class _Session:
    """Minimal stand-in: one row to find, and a record of what was added."""

    def __init__(
        self, row: ApplicationShare | None = None, *, application: object | None = object()
    ) -> None:
        self.row = row
        self.application = application
        self.added: list[object] = []

    async def get(self, _model: type, _pk: object) -> object | None:
        return self.application

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def scalar(self, *_a: object, **_k: object) -> object:
        return self.row

    async def scalars(self, *_a: object, **_k: object) -> list[object]:
        return [self.row] if self.row is not None else []


def _svc(row: ApplicationShare | None = None) -> ShareService:
    return ShareService(_Session(row), pepper=PEPPER)  # type: ignore[arg-type]


def _svc_without_application() -> ShareService:
    return ShareService(_Session(application=None), pepper=PEPPER)  # type: ignore[arg-type]


def _share(**over: object) -> ApplicationShare:
    row = ApplicationShare(
        application_id=uuid.uuid4(),
        token_hash=tokens.hash_token("t", PEPPER),
        expires_at=NOW + timedelta(days=1),
    )
    for k, v in over.items():
        setattr(row, k, v)
    return row


# -- tokens -------------------------------------------------------------------


def test_a_token_is_long_and_url_safe() -> None:
    """The URL is the only secret, so it carries session-token weight."""
    token = new_token()
    assert len(token) >= 32
    assert all(c.isalnum() or c in "-_" for c in token)


def test_two_tokens_are_never_the_same() -> None:
    assert len({new_token() for _ in range(50)}) == 50


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (None, DEFAULT_TTL_DAYS),
        (7, 7),
        (0, 1),
        (-5, 1),
        (10_000, MAX_TTL_DAYS),
    ],
)
def test_the_lifetime_is_bounded(asked: int | None, expected: int) -> None:
    """"Never expires" is not on offer: a forgotten link has to stop working by itself."""
    assert clamp_ttl(asked) == expected


# -- creating -----------------------------------------------------------------


async def test_create_stores_only_the_hash() -> None:
    """A stolen database must yield no working links."""
    svc = _svc()
    app_id = uuid.uuid4()
    row, token = await svc.create(app_id, actor="me", now=NOW)

    assert row.token_hash == tokens.hash_token(token, PEPPER)
    # The plaintext is nowhere on the row.
    assert token.encode() not in bytes(row.token_hash)
    assert row.created_by == "me"
    assert row.expires_at == NOW + timedelta(days=DEFAULT_TTL_DAYS)


async def test_creating_a_link_to_nothing_is_not_found() -> None:
    """A typo in the id must read as "no such application", not as a broken server.

    Without the check the INSERT trips the foreign key and the caller gets a 500 on a
    route that advertises 404.
    """
    with pytest.raises(NotFoundError):
        await _svc_without_application().create(uuid.uuid4(), actor="me", now=NOW)


async def test_create_honours_a_requested_lifetime_within_the_bound() -> None:
    row, _ = await _svc().create(uuid.uuid4(), actor="me", ttl_days=3, now=NOW)
    assert row.expires_at == NOW + timedelta(days=3)


# -- resolving ----------------------------------------------------------------


async def test_resolve_finds_a_live_link() -> None:
    row = _share()
    assert await _svc(row).resolve("t", now=NOW) is row


async def test_an_unknown_token_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _svc(None).resolve("nope", now=NOW)


async def test_an_expired_link_answers_the_same_as_an_unknown_one() -> None:
    """Never "this link expired": that tells a stranger they found a real one."""
    row = _share(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(NotFoundError):
        await _svc(row).resolve("t", now=NOW)


async def test_a_revoked_link_answers_the_same_as_an_unknown_one() -> None:
    row = _share(revoked_at=NOW - timedelta(days=1))
    with pytest.raises(NotFoundError):
        await _svc(row).resolve("t", now=NOW)


async def test_the_expiry_boundary_is_exclusive() -> None:
    # At exactly the expiry the link is gone. Erring towards closed is the right side.
    row = _share(expires_at=NOW)
    with pytest.raises(NotFoundError):
        await _svc(row).resolve("t", now=NOW)


async def test_a_wrong_token_does_not_resolve_a_row_that_exists() -> None:
    """The lookup is by hash, so a near-miss finds nothing rather than the wrong row."""
    row = _share()
    svc = ShareService(_Session(None), pepper=PEPPER)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.resolve("wrong", now=NOW)
    assert row.revoked_at is None


# -- revoking -----------------------------------------------------------------


async def test_revoke_stamps_the_time() -> None:
    row = _share()
    out = await _svc(row).revoke(row.id, application_id=row.application_id, now=NOW)
    assert out.revoked_at == NOW


async def test_revoking_twice_keeps_the_first_timestamp() -> None:
    first = NOW - timedelta(days=1)
    row = _share(revoked_at=first)
    out = await _svc(row).revoke(row.id, application_id=row.application_id, now=NOW)
    assert out.revoked_at == first


async def test_revoking_an_unknown_share_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _svc(None).revoke(uuid.uuid4(), application_id=uuid.uuid4(), now=NOW)


# -- the public view ----------------------------------------------------------


class _App:
    def __init__(self, data: dict[str, object]) -> None:
        self.id = uuid.uuid4()
        self.data = data
        self.amount: str | None = None
        self.currency: str | None = None
        self.created_at = NOW


def _field(key: str, *, pii: bool = False) -> FormFieldDef:
    return FormFieldDef.model_validate(
        {"key": key, "type": "text", "label": {"de": key.title()}, "isPII": pii}
    )


def test_the_public_view_drops_every_pii_field() -> None:
    """The same rule the gremium PDF applies, read from the same definitions."""
    view = build_public_view(
        _App({"title": "Fest", "zweck": "Musik", "iban": "DE00"}),  # type: ignore[arg-type]
        fields=[_field("zweck"), _field("iban", pii=True)],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    labels = [label for label, _ in view.fields]
    assert "Zweck" in labels
    assert "Iban" not in labels
    assert all("DE00" not in value for _, value in view.fields)


def test_the_public_view_skips_empty_answers() -> None:
    view = build_public_view(
        _App({"title": "Fest", "a": "", "b": None, "c": [], "d": "x"}),  # type: ignore[arg-type]
        fields=[_field(k) for k in ("a", "b", "c", "d")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert [label for label, _ in view.fields] == ["D"]


def test_an_application_without_a_title_still_has_a_heading() -> None:
    # A blank <h1> would make the preview a bare URL.
    view = build_public_view(
        _App({}),  # type: ignore[arg-type]
        fields=[],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.title


# -- the rendered page --------------------------------------------------------


def _view(**over: object) -> PublicApplication:
    base: dict[str, object] = {
        "title": "Anschaffung Beamer",
        "type_name": "Anschaffung",
        "gremium_name": "StuPa",
        "state_label": None,
        "amount": "4200.00",
        "currency": "EUR",
        "created_at": NOW,
        "fields": [("Zweck", "Musik")],
    }
    base.update(over)
    return PublicApplication(**base)  # type: ignore[arg-type]


def test_the_preview_carries_the_title_and_nothing_about_the_application() -> None:
    """The og: text lands permanently on a chat server we do not control."""
    html = render_share_page(_view(), app_name="STUPA", canonical_url="https://x/s/t")
    head = html.split("</head>")[0]

    assert 'property="og:title" content="Anschaffung Beamer — STUPA"' in head
    # The amount is on the page but must not be in the preview.
    assert "4200" not in head
    assert "Musik" not in head


def test_the_page_asks_not_to_be_indexed() -> None:
    # For whoever holds the URL, not for everyone who searches the applicant's name.
    html = render_share_page(_view(), app_name="STUPA", canonical_url="https://x/s/t")
    assert 'name="robots" content="noindex, nofollow"' in html


def test_every_value_is_escaped() -> None:
    """The page is hand-written HTML, so escaping is the one thing that must not slip."""
    html = render_share_page(
        _view(
            title='<script>alert(1)</script>',
            gremium_name='" onload="x',
            fields=[("<b>k</b>", "<img src=x onerror=y>")],
        ),
        app_name="STUPA",
        canonical_url="https://x/s/t",
    )
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert 'onload="x' not in html
    assert "&lt;script&gt;" in html


def test_a_missing_optional_leaves_its_row_out_rather_than_printing_none() -> None:
    html = render_share_page(
        _view(gremium_name=None, type_name=None, amount=None, currency=None),
        app_name="STUPA",
        canonical_url="https://x/s/t",
    )
    assert "None" not in html


# -- flattening one answer ----------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "shown"),
    [
        (True, "Ja"),
        (False, "Nein"),
        (["a", "b"], "a, b"),
        ([True, False], "Ja, Nein"),
        (42, "42"),
    ],
)
def test_an_answer_is_flattened_to_one_readable_line(answer: object, shown: str) -> None:
    view = build_public_view(
        _App({"title": "T", "k": answer}),  # type: ignore[arg-type]
        fields=[_field("k")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.fields == [("K", shown)]


def test_a_structured_answer_is_left_out_rather_than_guessed_at() -> None:
    """A dict has no sensible one-line form, and guessing one risks printing a key
    nobody meant to publish. The row goes with it — an empty value is not an answer."""
    view = build_public_view(
        _App({"title": "T", "k": {"iban": "DE00"}}),  # type: ignore[arg-type]
        fields=[_field("k")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.fields == []


def test_a_list_of_structured_rows_does_not_render_as_bare_commas() -> None:
    """A cost breakdown is a list of dicts. Joining them printed ", , ," — punctuation
    around values this page deliberately does not show."""
    view = build_public_view(
        _App({"title": "T", "k": [{"a": 1}, {"a": 2}, {"a": 3}]}),  # type: ignore[arg-type]
        fields=[_field("k")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.fields == []


def test_a_reference_field_does_not_publish_its_raw_id() -> None:
    """A select pointing at a cost centre holds that cost centre's UUID. On a public page
    the id names nothing the reader can use, and printing it publishes an internal
    identifier."""
    view = build_public_view(
        _App({"title": "T", "k": "83d149a5-9939-5d1c-b784-ee413e87f41e"}),  # type: ignore[arg-type]
        fields=[_field("k")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.fields == []


# -- the content security policy ----------------------------------------------


def test_the_policy_hash_matches_the_style_the_page_actually_renders() -> None:
    """The page shipped unstyled because the API-wide `default-src 'none'` blocked its
    own <style>. A hash fixes that only while it matches byte for byte, so this recomputes
    it from the rendered document rather than trusting the constant."""
    import base64
    import hashlib
    import re

    html = render_share_page(_view(), app_name="STUPA", canonical_url="https://x/s/t")
    css = re.search(r"<style>(.*?)</style>", html, re.S)
    assert css is not None
    digest = base64.b64encode(hashlib.sha256(css.group(1).encode()).digest()).decode()
    assert f"'sha256-{digest}'" in SHARE_CSP


def test_the_policy_allows_nothing_but_that_stylesheet() -> None:
    # No scripts, no images, no framing. The page is text and one stylesheet.
    assert SHARE_CSP.startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in SHARE_CSP
    assert "unsafe-inline" not in SHARE_CSP


def test_the_page_asks_for_no_favicon() -> None:
    """A browser requests /favicon.ico for any HTML page, and under this policy that
    request is refused and logged. An empty data: icon stops it being made."""
    html = render_share_page(_view(), app_name="STUPA", canonical_url="https://x/s/t")
    assert '<link rel="icon" href="data:,">' in html


# -- cost positions -----------------------------------------------------------
#
# A cost breakdown is the substance of a funding application: what the money is for, what
# it costs, and which quotes it was compared against. A public page that drops it shows
# the reader a title and hides what is being asked for.


def _positions_field(key: str = "kosten", *, pii: bool = False) -> FormFieldDef:
    return FormFieldDef.model_validate(
        {
            "key": key,
            "type": "positions",
            "label": {"de": "Kostenpositionen", "en": "Cost positions"},
            "isPII": pii,
        }
    )


#: Two positions: one compared against another quote, one that could not be compared.
POSITIONS: list[dict[str, object]] = [
    {
        "label": "Bühnentechnik",
        "offers": [
            {"label": "Firma A", "value": 1250, "preferred": True},
            {"label": "Firma B", "value": 1400},
        ],
    },
    {
        "label": "Catering",
        "noOffers": True,
        "noOffersReason": "einziger Anbieter vor Ort",
        "offers": [{"label": "Firma D", "value": 480, "preferred": True}],
    },
]


def _positions_view(lang: str = "de") -> PublicApplication:
    return build_public_view(
        _App({"title": "Fest", "kosten": POSITIONS}),  # type: ignore[arg-type]
        fields=[_positions_field()],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang=lang,
    )


def test_cost_positions_become_a_block_rather_than_one_flattened_line() -> None:
    """The whole point of the field is the breakdown. Flattening dropped it, so a funding
    application published its title and hid what it was asking for."""
    view = _positions_view()

    assert len(view.positions) == 1
    block = view.positions[0]
    assert block.label == "Kostenpositionen"
    assert [p.label for p in block.positions] == ["Bühnentechnik", "Catering"]


def test_a_position_is_worth_its_preferred_offer() -> None:
    """The same rule `positions_total` applies: the preferred offer is the position."""
    block = _positions_view().positions[0]
    assert block.positions[0].value == "1.250,00 €"
    assert block.total == "1.730,00 €"


def test_every_comparison_offer_is_shown_and_the_preferred_one_is_marked() -> None:
    # A reader cannot check "we took the cheapest" without seeing what it was compared
    # against, so the losing quotes are part of the answer rather than noise.
    offers = _positions_view().positions[0].positions[0].offers
    assert [(o.label, o.value, o.preferred) for o in offers] == [
        ("Firma A", "1.250,00 €", True),
        ("Firma B", "1.400,00 €", False),
    ]


def test_a_position_without_comparison_offers_carries_its_reason() -> None:
    """Opting out is allowed, and the reason is the justification for it. The opt-out
    without its reason reads as a missing comparison rather than an explained one."""
    catering = _positions_view().positions[0].positions[1]
    assert catering.no_offers_reason == "einziger Anbieter vor Ort"


def test_a_positions_field_marked_pii_never_reaches_the_page() -> None:
    """`isPII` is one rule for every field type. A structured field must not be the hole
    in it."""
    view = build_public_view(
        _App({"title": "Fest", "kosten": POSITIONS}),  # type: ignore[arg-type]
        fields=[_positions_field(pii=True)],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.positions == []


def test_a_positions_field_does_not_also_appear_as_a_flattened_row() -> None:
    # It is rendered as a block. A second, empty scalar row for the same field would be
    # the same field printed twice.
    assert [label for label, _ in _positions_view().fields] == []


def test_a_broken_position_is_skipped_rather_than_crashing_the_page() -> None:
    """The answer is JSONB written by an older form version, so the page cannot assume
    the current shape. A public route that raises here is a 500 on a valid link."""
    view = build_public_view(
        _App({"title": "T", "kosten": ["nope", {"offers": "not a list"}]}),  # type: ignore[arg-type]
        fields=[_positions_field()],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.positions == []


# -- the remaining field types ------------------------------------------------


def _typed(key: str, type_: str, **extra: object) -> FormFieldDef:
    return FormFieldDef.model_validate(
        {"key": key, "type": type_, "label": {"de": key.title()}, **extra}
    )


def _one(field: FormFieldDef, value: object, lang: str = "de") -> list[tuple[str, str]]:
    return build_public_view(
        _App({"title": "T", field.key: value}),  # type: ignore[arg-type]
        fields=[field],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang=lang,
    ).fields


def test_a_select_shows_the_option_label_and_not_the_stored_value() -> None:
    """The stored value is a machine key such as `av`. Printing it publishes the form's
    internals and tells the reader nothing."""
    field = _typed(
        "medium", "select", options=[{"value": "av", "label": {"de": "Audio und Video"}}]
    )
    assert _one(field, "av") == [("Medium", "Audio und Video")]


def test_a_multiselect_joins_its_option_labels() -> None:
    field = _typed(
        "tags",
        "multiselect",
        options=[
            {"value": "a", "label": {"de": "Kultur"}},
            {"value": "b", "label": {"de": "Sport"}},
        ],
    )
    assert _one(field, ["a", "b"]) == [("Tags", "Kultur, Sport")]


def test_a_currency_field_reads_as_money_rather_than_a_bare_number() -> None:
    assert _one(_typed("kosten", "currency"), 1250) == [("Kosten", "1.250,00 €")]


def test_a_date_range_reads_as_a_span() -> None:
    """`{'from': ..., 'to': ...}` is a dict, so the old rule dropped it entirely."""
    field = _typed("zeitraum", "daterange")
    value = {"from": "2026-07-01", "to": "2026-07-03"}
    assert _one(field, value) == [("Zeitraum", "01.07.2026 – 03.07.2026")]


def test_a_date_reads_in_the_house_format() -> None:
    # `%d.%m.%Y`, the format the protocol and the notification mails already use.
    assert _one(_typed("tag", "date"), "2026-07-01") == [("Tag", "01.07.2026")]


def test_an_unreadable_date_is_shown_as_stored_rather_than_dropped() -> None:
    """A date the form never validated is still the applicant's answer. Guessing it away
    loses information; printing it as stored is honest."""
    assert _one(_typed("tag", "date"), "irgendwann") == [("Tag", "irgendwann")]


# -- the rendered breakdown, the portal button and the logo -------------------


def test_the_page_renders_every_position_with_its_offers() -> None:
    html = render_share_page(
        _positions_view(), app_name="STUPA", canonical_url="https://x/s/t"
    )
    for expected in (
        "Kostenpositionen",
        "Bühnentechnik",
        "Firma A",
        "Firma B",
        "1.250,00 €",
        "1.400,00 €",
        "einziger Anbieter vor Ort",
        "1.730,00 €",
    ):
        assert expected in html


def test_the_breakdown_stays_out_of_the_link_preview() -> None:
    """Same rule as the amount: what the meta tags carry lands on a chat server for good."""
    html = render_share_page(
        _positions_view(), app_name="STUPA", canonical_url="https://x/s/t"
    )
    head = html.split("</head>")[0]
    assert "Firma A" not in head
    assert "1.730" not in head


def test_a_position_label_is_escaped_like_every_other_value() -> None:
    view = build_public_view(
        _App(  # type: ignore[arg-type]
            {
                "title": "T",
                "kosten": [
                    {
                        "label": "<script>alert(1)</script>",
                        "offers": [{"label": "<img>", "value": 5, "preferred": True}],
                    }
                ],
            }
        ),
        fields=[_positions_field()],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    html = render_share_page(view, app_name="STUPA", canonical_url="https://x/s/t")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img>" not in html


def test_the_page_offers_a_way_into_the_portal() -> None:
    """A reader who has an account should not have to find the application by hand. The
    link goes to the record itself, and a reader without an account meets the login."""
    html = render_share_page(
        _view(),
        app_name="STUPA",
        canonical_url="https://x/s/t",
        app_url="https://x/applications/abc",
    )
    assert 'href="https://x/applications/abc"' in html


def test_without_a_portal_url_there_is_no_dead_button() -> None:
    html = render_share_page(_view(), app_name="STUPA", canonical_url="https://x/s/t")
    assert "applications/" not in html


def test_the_page_carries_the_instance_logo_when_there_is_one() -> None:
    """The one piece of branding this platform really holds per instance."""
    html = render_share_page(
        _view(),
        app_name="STUPA",
        canonical_url="https://x/s/t",
        logo_url="https://cdn.example/logo.png",
    )
    assert '<img class="brand__logo" src="https://cdn.example/logo.png"' in html


def test_a_logo_served_over_plain_http_is_left_off() -> None:
    """It would be mixed content, and it would tell that host the IP of every reader who
    opens the link."""
    html = render_share_page(
        _view(),
        app_name="STUPA",
        canonical_url="https://x/s/t",
        logo_url="http://cdn.example/logo.png",
    )
    assert "cdn.example" not in html
    assert "STUPA" in html


def test_the_policy_names_the_logo_source_and_nothing_wider() -> None:
    """`img-src https:` would allow any host on the internet. The page loads exactly one
    image, so the policy names exactly where it comes from."""
    assert "img-src 'none'" in share_csp(None)
    assert "img-src data:" in share_csp("data:image/png;base64,AAAA")
    assert "img-src https://cdn.example" in share_csp("https://cdn.example/logo.png")
    assert "img-src 'none'" in share_csp("http://cdn.example/logo.png")


def test_the_policy_still_allows_no_script_whatever_the_logo() -> None:
    for logo in (None, "data:image/png;base64,AAAA", "https://cdn.example/l.png"):
        policy = share_csp(logo)
        assert policy.startswith("default-src 'none'")
        assert "script-src" not in policy
        assert "unsafe-inline" not in policy


# -- the edges of the formatting ----------------------------------------------


def test_an_english_page_reads_money_the_english_way() -> None:
    """The route already knows the language of the application. A German number format
    around English labels would be a choice rather than an oversight."""
    assert _one(_typed("kosten", "currency"), 1250, lang="en") == [
        ("Kosten", "€1,250.00")
    ]


def test_a_currency_other_than_the_euro_is_named_rather_than_symbolised() -> None:
    """`amount`/`currency` are per application, so the page cannot assume the euro."""
    app = _App({"title": "T", "kosten": 1250})
    app.currency = "CHF"
    view = build_public_view(
        app,  # type: ignore[arg-type]
        fields=[_typed("kosten", "currency")],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.fields == [("Kosten", "1.250,00 CHF")]


def test_a_currency_field_that_holds_no_number_falls_back_to_the_plain_rule() -> None:
    assert _one(_typed("kosten", "currency"), "auf Anfrage") == [
        ("Kosten", "auf Anfrage")
    ]


def test_the_headline_amount_is_written_like_the_breakdown_below_it() -> None:
    """It was the stored decimal joined to the currency code, so one page showed
    "4200.00 EUR" above "1.730,00 €" — the same kind of number written two ways."""
    html = render_share_page(_view(), app_name="STUPA", canonical_url="https://x/s/t")
    assert "4.200,00 €" in html
    assert "4200.00" not in html


def test_an_amount_that_will_not_parse_is_still_shown() -> None:
    html = render_share_page(
        _view(amount="etwa 4200", currency="EUR"),
        app_name="STUPA",
        canonical_url="https://x/s/t",
    )
    assert "etwa 4200 EUR" in html


def test_a_boolean_is_never_read_as_an_amount() -> None:
    """`Decimal(str(True))` raises, but `True` also equals 1, and an application that
    quietly claims to cost one euro would be worse than one that reads oddly."""
    assert _one(_typed("kosten", "currency"), True) == [("Kosten", "Ja")]


def test_a_half_filled_date_range_shows_the_half_it_has() -> None:
    field = _typed("zeitraum", "daterange")
    assert _one(field, {"from": "2026-07-01"}) == [("Zeitraum", "01.07.2026")]
    assert _one(field, {"from": "", "to": ""}) == []


def test_a_date_that_is_not_even_text_takes_the_plain_rule() -> None:
    assert _one(_typed("tag", "date"), 20260701) == [("Tag", "20260701")]


def test_an_option_without_a_label_falls_back_to_its_value() -> None:
    """A form saved with an empty label should still name the answer somehow."""
    field = _typed("medium", "select", options=[{"value": "av", "label": {}}])
    assert _one(field, "av") == [("Medium", "av")]


def test_an_answer_that_matches_no_option_is_not_invented() -> None:
    """A stale answer from an older form version. The id rule still applies."""
    field = _typed("medium", "select", options=[{"value": "av", "label": {"de": "AV"}}])
    assert _one(field, "83d149a5-9939-5d1c-b784-ee413e87f41e") == []


def test_an_unreadable_offer_is_skipped_rather_than_shown_as_zero() -> None:
    """`positions` is JSONB. An offer with no usable value must not become "0,00 €",
    which would read as a free quote."""
    view = build_public_view(
        _App(  # type: ignore[arg-type]
            {
                "title": "T",
                "kosten": [
                    {
                        "label": "Technik",
                        "offers": [
                            "not an offer",
                            {"label": "kein Preis", "value": "tbd"},
                            {"label": "Firma A", "value": 100, "preferred": True},
                        ],
                    }
                ],
            }
        ),
        fields=[_positions_field()],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    offers = view.positions[0].positions[0].offers
    assert [o.label for o in offers] == ["Firma A"]


def test_a_position_with_no_preferred_offer_shows_its_quotes_and_no_value() -> None:
    """An application still being put together. Showing nothing would hide the quotes it
    already has; inventing a value would state a decision nobody made."""
    view = build_public_view(
        _App(  # type: ignore[arg-type]
            {
                "title": "T",
                "kosten": [
                    {"label": "Technik", "offers": [{"label": "Firma A", "value": 100}]}
                ],
            }
        ),
        fields=[_positions_field()],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    block = view.positions[0]
    assert block.positions[0].value is None
    assert block.total is None
    assert len(block.positions[0].offers) == 1

    # And the page prints no total line rather than a total of nothing.
    html = render_share_page(view, app_name="STUPA", canonical_url="https://x/s/t")
    assert "Firma A" in html
    assert "Gesamtbetrag" not in html


def test_a_positions_answer_that_is_not_a_list_is_left_out() -> None:
    view = build_public_view(
        _App({"title": "T", "kosten": "kostet halt was"}),  # type: ignore[arg-type]
        fields=[_positions_field()],
        type_name=None,
        gremium_name=None,
        state_label=None,
        lang="de",
    )
    assert view.positions == []
    assert view.fields == []
