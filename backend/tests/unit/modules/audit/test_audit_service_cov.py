"""Extra branch and line coverage for `AuditService` (T-23).

These tests cover the branches that the base unit test misses. They drive
`query_cursor` with and without filters and at the `has_more` limit. They drive
`resolve_actor_names` with an empty and a full input and with the None fallback. They
drive `resolve_target_labels` through every type branch, an invalid UUID, the i18n
fallbacks and the empty or None label paths. They also drive `list_actors`.

The tests need no database. The result-queue fakes in `tests._support.audit_fakes`
serve `execute` and `stream_scalars`. Each `execute(...).all()` call returns the given
items in order. The resolvers receive tuples.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.audit.models import AuditEntry
from app.modules.audit.service import AuditService
from tests._support.audit_fakes import fake_session, result

_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


def _uuid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n, version=4)


async def test_query_cursor_no_filters_under_limit() -> None:
    """Without a filter and with fewer rows than `limit`, `has_more` stays False."""
    rows = ["e3", "e2", "e1"]
    db = fake_session(result(*rows))
    items, has_more = await AuditService(db).query_cursor(limit=5)
    assert items == rows
    assert has_more is False


async def test_query_cursor_all_filters_and_has_more() -> None:
    """All filter branches read `limit+1` rows, so `has_more` is True and the list trims."""
    rows = ["e3", "e2", "e1"]  # limit=2, so three rows are read
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
    """Exactly `limit` rows means there is no further page."""
    rows = ["e2", "e1"]
    db = fake_session(result(*rows))
    items, has_more = await AuditService(db).query_cursor(limit=2)
    assert items == rows
    assert has_more is False


async def test_resolve_actor_names_empty_input_short_circuits() -> None:
    """Only None or empty subs give an empty map without a database access."""
    db = fake_session()  # no results needed
    out = await AuditService(db).resolve_actor_names([None, None])
    assert out == {}


async def test_resolve_actor_names_prefers_display_name_else_email() -> None:
    """The display_name wins, otherwise the email fallback applies (both `or` branches)."""
    rows = [
        ("sub-1", "Alice", "alice@example.org"),
        ("sub-2", None, "bob@example.org"),
    ]
    db = fake_session(result(*rows))
    out = await AuditService(db).resolve_actor_names(["sub-1", "sub-2", None])
    assert out == {"sub-1": "Alice", "sub-2": "bob@example.org"}


async def test_resolve_target_labels_empty_and_invalid_targets() -> None:
    """A None type or id and a non-UUID id are skipped, so no query runs and the map is empty."""
    db = fake_session()
    out = await AuditService(db).resolve_target_labels(
        [
            (None, "x"),  # no target_type
            ("application", None),  # no target_id
            ("application", "export-2026.csv"),  # not a UUID, so ValueError continues
        ]
    )
    assert out == {}


async def test_resolve_target_labels_application_title_branches() -> None:
    """An application keeps a valid title. An empty or non-string title is ignored."""
    ok = _uuid(1)
    blank = _uuid(2)
    missing = _uuid(3)
    rows = [
        (ok, {"title": "  Mein Antrag  "}),  # taken with the whitespace trimmed
        (blank, {"title": "   "}),  # only whitespace, so ignored
        (missing, {}),  # no title, so ignored
        (_uuid(4), {"title": 123}),  # not a string, so ignored
        (_uuid(5), None),  # data None hits the (data or {}) fallback
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
    """Both `fill` branches run: it sets a label and skips an empty label."""
    g_ok = _uuid(10)
    g_empty = _uuid(11)
    w_ok = _uuid(12)
    # The execute calls run in this order: gremium, then webhook.
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
    """The i18n label prefers 'de', otherwise the first value. Empty or non-dict gives None."""
    a_de = _uuid(20)
    a_other = _uuid(21)
    a_empty = _uuid(22)
    a_nondict = _uuid(23)
    rows = [
        (a_de, {"de": "Antrag", "en": "Application"}),  # de wins
        (a_other, {"en": "Only EN"}),  # no de, so the first value wins
        (a_empty, {}),  # an empty dict gives None, so no label
        (a_nondict, None),  # not a dict, so None and no label
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
    """A role prefers the i18n label, otherwise `key`. Without both there is no entry."""
    r_i18n = _uuid(30)
    r_key = _uuid(31)
    r_none = _uuid(32)
    rows = [
        (r_i18n, {"de": "Administrator"}, "admin"),  # i18n wins
        (r_key, {}, "treasurer"),  # empty i18n falls back to key
        (r_none, None, None),  # nothing, so no label
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
    """A principal prefers display_name, otherwise email. Without both there is no entry."""
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
    """The vote and attachment types run through `fill` and cover both label branches."""
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
    """An unknown type parses, but no block resolves it."""
    unknown = _uuid(60)
    db = fake_session()  # no block matches, so no execute runs
    out = await AuditService(db).resolve_target_labels([("session", str(unknown))])
    assert out == {}


async def test_resolve_target_labels_all_types_together() -> None:
    """All known types together make every `if ids :=` branch truthy.

    The execute calls follow the source order: application, gremium, application_type,
    role, principal, webhook, vote and attachment.
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


async def test_list_actors_resolves_names() -> None:
    """The result holds distinct subs with resolved names. A None sub is filtered out."""
    # The first execute serves scalars().all() for the subs. The second execute runs
    # inside resolve_actor_names and returns the name rows.
    subs = ["sub-1", "sub-2", None]
    name_rows = [
        ("sub-1", "Alice", "alice@example.org"),
        ("sub-2", None, "bob@example.org"),
    ]
    db = fake_session(result(*subs), result(*name_rows))
    out = await AuditService(db).list_actors()
    assert out == [("sub-1", "Alice"), ("sub-2", "bob@example.org")]


async def test_list_actors_empty_log() -> None:
    """Without an actor the resolve step short-circuits and needs no second query."""
    db = fake_session(result())
    out = await AuditService(db).list_actors()
    assert out == []


async def test_resolve_data_ids_no_uuids_short_circuits() -> None:
    """Without a UUID-shaped value the method returns early with an empty map."""
    db = fake_session()  # no query expected
    out = await AuditService(db).resolve_data_ids([{"k": "nicht-uuid", "n": 7}, None])
    assert out == {}


async def test_resolve_data_ids_all_entity_branches() -> None:
    """Cover every resolution branch of resolve_data_ids.

    The test covers each table hit, the i18n fallbacks and the empty or None label. It
    also covers the `str(id) not in labels` dedup path, where the same UUID appears in
    several tables.

    The execute calls follow this order: application, gremium, budget, meeting, webhook,
    vote, attachment, principal, role, application_type and fiscal_year.
    """
    a1 = _uuid(1)  # application, wins and appears again in later tables (dedup)
    a_blank, a_missing, a_nonstr, a_nodata = _uuid(2), _uuid(3), _uuid(4), _uuid(5)
    g_ok, g_empty = _uuid(10), _uuid(11)
    bud, meet, vote, attach = _uuid(20), _uuid(30), _uuid(40), _uuid(50)
    p_name, p_email, p_none = _uuid(60), _uuid(61), _uuid(62)
    r_i18n, r_key, r_none = _uuid(70), _uuid(71), _uuid(72)
    t_de, t_other, t_empty, t_nondict = _uuid(80), _uuid(81), _uuid(82), _uuid(83)
    fy = _uuid(90)

    db = fake_session(
        result(  # application: title trimmed. blank, missing, non-string, None ignored
            (a1, {"title": "  Antrag  "}),
            (a_blank, {"title": "   "}),
            (a_missing, {}),
            (a_nonstr, {"title": 123}),
            (a_nodata, None),
        ),
        result((g_ok, "Vorstand"), (g_empty, ""), (a1, "DupG")),  # fill: ok, empty, dup
        result((bud, "Budget X")),  # budget
        result((meet, "Sitzung")),  # meeting
        result(),  # webhook: no hits
        result((vote, "Frage?")),  # vote
        result((attach, "f.pdf")),  # attachment
        result(  # principal: name, email fallback, none, dup
            (p_name, "Carol", "c@e"),
            (p_email, None, "d@e"),
            (p_none, None, None),
            (a1, "DupP", "x@e"),
        ),
        result(  # role: i18n, key fallback, none, dup
            (r_i18n, {"de": "Administrator"}, "admin"),
            (r_key, {}, "treas"),
            (r_none, None, None),
            (a1, {"de": "DupR"}, "k"),
        ),
        result(  # application_type: de, first value, empty, non-dict, dup
            (t_de, {"de": "Antrag"}),
            (t_other, {"en": "EN only"}),
            (t_empty, {}),
            (t_nondict, None),
            (a1, {"de": "DupT"}),
        ),
        result((fy, 2026), (a1, 2030)),  # fiscal_year: year string, dup
    )

    out = await AuditService(db).resolve_data_ids(
        [{"ref": str(a1)}, {"nested": {"x": str(g_ok)}}]
    )
    assert out == {
        str(a1): "Antrag",
        str(g_ok): "Vorstand",
        str(bud): "Budget X",
        str(meet): "Sitzung",
        str(vote): "Frage?",
        str(attach): "f.pdf",
        str(p_name): "Carol",
        str(p_email): "d@e",
        str(r_i18n): "Administrator",
        str(r_key): "treas",
        str(t_de): "Antrag",
        str(t_other): "EN only",
        str(fy): "2026",
    }


async def test_revertable_flags_classifies_actions() -> None:
    """Classify each action type and data shape as revertable or not (#config-versioning).

    A config change needs a predecessor, which the batch lookup provides. A budget change
    needs the recorded previous state. A delete and an unknown action never revert.
    """
    rev_a, prev_a, rev_b = _uuid(1), _uuid(2), _uuid(3)
    entries = [
        AuditEntry(id=1, action="config_change", data={"revisionId": str(rev_a)}),
        AuditEntry(id=2, action="config_change", data={"revisionId": str(rev_b)}),
        AuditEntry(
            id=3, action="status_change", data={"fromStateId": "a", "toStateId": "b"}
        ),
        AuditEntry(id=4, action="status_change", data={"toStateId": "b"}),
        AuditEntry(id=5, action="budget_node_create", data={}),
        AuditEntry(id=6, action="budget_node_update", data={"before": {"name": "x"}}),
        AuditEntry(id=7, action="budget_node_update", data={"fields": ["name"]}),
        AuditEntry(
            id=8, action="budget_allocation_set", data={"previousAllocated": None}
        ),
        AuditEntry(id=9, action="budget_allocation_set", data={"allocated": "5"}),
        AuditEntry(id=10, action="budget_expense_delete", data={}),
        AuditEntry(id=11, action="login", data={}),
    ]
    # Predecessor lookup of the config snapshots: rev_a has one, rev_b is the first.
    db = fake_session(result((rev_a, prev_a), (rev_b, None)))
    flags = await AuditService(db).revertable_flags(entries)
    assert flags == {
        1: True,
        2: False,
        3: True,
        4: False,
        5: True,
        6: True,
        7: False,
        8: True,
        9: False,
        10: False,
        11: False,
    }


async def test_revertable_flags_no_config_entries_skips_lookup() -> None:
    """Without a config entry, which means without a revisionId, the lookup is skipped."""
    entries = [
        AuditEntry(id=1, action="status_change", data={"fromStateId": "a", "toStateId": "b"}),
        AuditEntry(id=2, action="login", data={}),
    ]
    flags = await AuditService(fake_session()).revertable_flags(entries)
    assert flags == {1: True, 2: False}


async def test_revertable_flags_invalid_revision_id_is_not_revertable() -> None:
    """A broken revisionId leaves uuid_map empty, skips the lookup and blocks the revert."""
    entries = [AuditEntry(id=1, action="config_change", data={"revisionId": "not-a-uuid"})]
    flags = await AuditService(fake_session()).revertable_flags(entries)
    assert flags == {1: False}


async def test_revertable_flags_ignores_unrequested_revision_rows() -> None:
    """A lookup row that belongs to no entry is skipped, because eid is None."""
    rev_a, prev_a, foreign = _uuid(1), _uuid(2), _uuid(9)
    entries = [AuditEntry(id=1, action="config_change", data={"revisionId": str(rev_a)})]
    db = fake_session(result((rev_a, prev_a), (foreign, None)))
    flags = await AuditService(db).revertable_flags(entries)
    assert flags == {1: True}
