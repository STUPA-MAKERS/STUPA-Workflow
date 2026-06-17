"""Branch-/Line-Coverage-Ergänzung für ``AuditService`` (T-23).

Deckt die im Basis-Unit-Test fehlenden Zweige ab: ``query_cursor`` mit/ohne
Filter und ``has_more``-Grenze, ``resolve_actor_names`` (leer/voll, None-Fallback),
``resolve_target_labels`` (alle Typ-Zweige, ungültige UUID, i18n-Fallbacks,
leere/None-Label-Pfade) sowie ``list_actors``.

Unit-only ohne DB: ``execute``/``stream_scalars`` über die Ergebnis-Queue-Fakes
(``tests._support.audit_fakes``); ``execute(...).all()`` liefert die übergebenen
Items (für die Resolver Tupel) der Reihe nach.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.audit.service import AuditService
from tests._support.audit_fakes import fake_session, result

_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


def _uuid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n, version=4)


# ------------------------------------------------------------------- query_cursor
async def test_query_cursor_no_filters_under_limit() -> None:
    """Ohne Filter, weniger Zeilen als ``limit`` → ``has_more`` False."""
    rows = ["e3", "e2", "e1"]
    db = fake_session(result(*rows))
    items, has_more = await AuditService(db).query_cursor(limit=5)
    assert items == rows
    assert has_more is False


async def test_query_cursor_all_filters_and_has_more() -> None:
    """Alle Filterzweige + ``limit+1`` gelesen → ``has_more`` True, Trim auf ``limit``."""
    rows = ["e3", "e2", "e1"]  # limit=2 → 3 Zeilen gelesen
    db = fake_session(result(*rows))
    items, has_more = await AuditService(db).query_cursor(
        action="login",
        actor="a",
        since=_AT,
        until=_AT,
        before=99,
        limit=2,
    )
    assert items == ["e3", "e2"]
    assert has_more is True


async def test_query_cursor_exactly_limit_has_no_more() -> None:
    """Genau ``limit`` Zeilen → keine weitere Seite."""
    rows = ["e2", "e1"]
    db = fake_session(result(*rows))
    items, has_more = await AuditService(db).query_cursor(limit=2)
    assert items == rows
    assert has_more is False


# -------------------------------------------------------------- resolve_actor_names
async def test_resolve_actor_names_empty_input_short_circuits() -> None:
    """Nur None/leere subs → kein DB-Zugriff, leere Map."""
    db = fake_session()  # keine Ergebnisse nötig
    out = await AuditService(db).resolve_actor_names([None, None])
    assert out == {}


async def test_resolve_actor_names_prefers_display_name_else_email() -> None:
    """display_name bevorzugt, sonst email-Fallback (beide Zweige des ``or``)."""
    rows = [
        ("sub-1", "Alice", "alice@example.org"),
        ("sub-2", None, "bob@example.org"),
    ]
    db = fake_session(result(*rows))
    out = await AuditService(db).resolve_actor_names(["sub-1", "sub-2", None])
    assert out == {"sub-1": "Alice", "sub-2": "bob@example.org"}


# ----------------------------------------------------------- resolve_target_labels
async def test_resolve_target_labels_empty_and_invalid_targets() -> None:
    """None-Typ/Id und nicht-UUID-Id werden übersprungen → leere Map, kein Query."""
    db = fake_session()
    out = await AuditService(db).resolve_target_labels(
        [
            (None, "x"),  # kein target_type
            ("application", None),  # keine target_id
            ("application", "export-2026.csv"),  # keine UUID → ValueError-continue
        ]
    )
    assert out == {}


async def test_resolve_target_labels_application_title_branches() -> None:
    """application: gültiger Titel gesetzt; leerer/Nicht-String-Titel ignoriert."""
    ok = _uuid(1)
    blank = _uuid(2)
    missing = _uuid(3)
    rows = [
        (ok, {"title": "  Mein Antrag  "}),  # getrimmt übernommen
        (blank, {"title": "   "}),  # nur Whitespace → ignoriert
        (missing, {}),  # kein Titel → ignoriert
        (_uuid(4), {"title": 123}),  # kein String → ignoriert
        (_uuid(5), None),  # data None → (data or {}) Fallback
    ]
    db = fake_session(result(*rows))
    out = await AuditService(db).resolve_target_labels(
        [
            ("application", str(ok)),
            ("application", str(blank)),
            ("application", str(missing)),
            ("application", str(_uuid(4))),
            ("application", str(_uuid(5))),
        ]
    )
    assert out == {("application", str(ok)): "Mein Antrag"}


async def test_resolve_target_labels_gremium_and_webhook_fill() -> None:
    """``fill``: Label gesetzt vs. leeres Label übersprungen (beide Zweige)."""
    g_ok = _uuid(10)
    g_empty = _uuid(11)
    w_ok = _uuid(12)
    # Reihenfolge der execute-Aufrufe: gremium, dann webhook
    gremium_rows = [(g_ok, "Vorstand"), (g_empty, "")]
    webhook_rows = [(w_ok, "Slack")]
    db = fake_session(result(*gremium_rows), result(*webhook_rows))
    out = await AuditService(db).resolve_target_labels(
        [
            ("gremium", str(g_ok)),
            ("gremium", str(g_empty)),
            ("webhook", str(w_ok)),
        ]
    )
    assert out == {
        ("gremium", str(g_ok)): "Vorstand",
        ("webhook", str(w_ok)): "Slack",
    }


async def test_resolve_target_labels_application_type_i18n_branches() -> None:
    """i18n_label: 'de' bevorzugt, sonst erster Wert, None bei leer/kein-dict."""
    a_de = _uuid(20)
    a_other = _uuid(21)
    a_empty = _uuid(22)
    a_nondict = _uuid(23)
    rows = [
        (a_de, {"de": "Antrag", "en": "Application"}),  # de bevorzugt
        (a_other, {"en": "Only EN"}),  # kein de → erster Wert
        (a_empty, {}),  # leeres dict → None → kein Label
        (a_nondict, None),  # kein dict → None → kein Label
    ]
    db = fake_session(result(*rows))
    out = await AuditService(db).resolve_target_labels(
        [
            ("application_type", str(a_de)),
            ("application_type", str(a_other)),
            ("application_type", str(a_empty)),
            ("application_type", str(a_nondict)),
        ]
    )
    assert out == {
        ("application_type", str(a_de)): "Antrag",
        ("application_type", str(a_other)): "Only EN",
    }


async def test_resolve_target_labels_role_i18n_then_key_fallback() -> None:
    """role: i18n-Label bevorzugt, sonst ``key``; ohne beides kein Eintrag."""
    r_i18n = _uuid(30)
    r_key = _uuid(31)
    r_none = _uuid(32)
    rows = [
        (r_i18n, {"de": "Administrator"}, "admin"),  # i18n gewinnt
        (r_key, {}, "treasurer"),  # i18n leer → key
        (r_none, None, None),  # nichts → kein Label
    ]
    db = fake_session(result(*rows))
    out = await AuditService(db).resolve_target_labels(
        [
            ("role", str(r_i18n)),
            ("role", str(r_key)),
            ("role", str(r_none)),
        ]
    )
    assert out == {
        ("role", str(r_i18n)): "Administrator",
        ("role", str(r_key)): "treasurer",
    }


async def test_resolve_target_labels_principal_name_then_email() -> None:
    """principal: display_name bevorzugt, sonst email; ohne beides kein Eintrag."""
    p_name = _uuid(40)
    p_email = _uuid(41)
    p_none = _uuid(42)
    rows = [
        (p_name, "Carol", "carol@example.org"),
        (p_email, None, "dave@example.org"),
        (p_none, None, None),
    ]
    db = fake_session(result(*rows))
    out = await AuditService(db).resolve_target_labels(
        [
            ("principal", str(p_name)),
            ("principal", str(p_email)),
            ("principal", str(p_none)),
        ]
    )
    assert out == {
        ("principal", str(p_name)): "Carol",
        ("principal", str(p_email)): "dave@example.org",
    }


async def test_resolve_target_labels_vote_and_attachment_fill() -> None:
    """vote + attachment laufen über ``fill`` (beide Zweige der Label-Prüfung)."""
    v_ok = _uuid(50)
    v_empty = _uuid(51)
    at_ok = _uuid(52)
    vote_rows = [(v_ok, "Soll X beschlossen werden?"), (v_empty, None)]
    attachment_rows = [(at_ok, "beleg.pdf")]
    db = fake_session(result(*vote_rows), result(*attachment_rows))
    out = await AuditService(db).resolve_target_labels(
        [
            ("vote", str(v_ok)),
            ("vote", str(v_empty)),
            ("attachment", str(at_ok)),
        ]
    )
    assert out == {
        ("vote", str(v_ok)): "Soll X beschlossen werden?",
        ("attachment", str(at_ok)): "beleg.pdf",
    }


async def test_resolve_target_labels_unknown_type_no_query() -> None:
    """Unbekannter Typ wird zwar geparst, aber von keinem Block aufgelöst."""
    unknown = _uuid(60)
    db = fake_session()  # kein Block trifft → kein execute
    out = await AuditService(db).resolve_target_labels([("session", str(unknown))])
    assert out == {}


async def test_resolve_target_labels_all_types_together() -> None:
    """Alle bekannten Typen gemeinsam → jeder ``if ids :=``-Zweig ist truthy.

    Reihenfolge der execute-Aufrufe entspricht der Quell-Reihenfolge:
    application, gremium, application_type, role, principal, webhook, vote, attachment.
    """
    app_id = _uuid(100)
    grem_id = _uuid(101)
    at_id = _uuid(102)
    role_id = _uuid(103)
    princ_id = _uuid(104)
    hook_id = _uuid(105)
    vote_id = _uuid(106)
    attach_id = _uuid(107)
    db = fake_session(
        result((app_id, {"title": "Antrag A"})),
        result((grem_id, "Vorstand")),
        result((at_id, {"de": "Typ"})),
        result((role_id, {"de": "Admin"}, "admin")),
        result((princ_id, "Eve", "eve@example.org")),
        result((hook_id, "Webhook 1")),
        result((vote_id, "Frage?")),
        result((attach_id, "datei.pdf")),
    )
    out = await AuditService(db).resolve_target_labels(
        [
            ("application", str(app_id)),
            ("gremium", str(grem_id)),
            ("application_type", str(at_id)),
            ("role", str(role_id)),
            ("principal", str(princ_id)),
            ("webhook", str(hook_id)),
            ("vote", str(vote_id)),
            ("attachment", str(attach_id)),
        ]
    )
    assert out == {
        ("application", str(app_id)): "Antrag A",
        ("gremium", str(grem_id)): "Vorstand",
        ("application_type", str(at_id)): "Typ",
        ("role", str(role_id)): "Admin",
        ("principal", str(princ_id)): "Eve",
        ("webhook", str(hook_id)): "Webhook 1",
        ("vote", str(vote_id)): "Frage?",
        ("attachment", str(attach_id)): "datei.pdf",
    }


# ----------------------------------------------------------------------- list_actors
async def test_list_actors_resolves_names() -> None:
    """Distinkte subs + aufgelöste Klarnamen; None-subs werden gefiltert."""
    # 1. execute → scalars().all() der subs; 2. execute (in resolve_actor_names) → rows
    subs = ["sub-1", "sub-2", None]
    name_rows = [
        ("sub-1", "Alice", "alice@example.org"),
        ("sub-2", None, "bob@example.org"),
    ]
    db = fake_session(result(*subs), result(*name_rows))
    out = await AuditService(db).list_actors()
    assert out == [("sub-1", "Alice"), ("sub-2", "bob@example.org")]


async def test_list_actors_empty_log() -> None:
    """Keine Akteure → resolve kurzschließt (keine zweite Abfrage nötig)."""
    db = fake_session(result())
    out = await AuditService(db).list_actors()
    assert out == []
