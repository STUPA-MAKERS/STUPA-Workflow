"""Full coverage of ``ConfigService`` without a DB (app/modules/admin/service/).

These tests drive every CRUD path plus all mappers and the guard, conflict and
not-found branches. The paths cover gremium, application type, global flow, roles,
assignments, principals, group mappings and webhooks.

A custom ``AsyncSession`` fake replaces Docker, Redis and Postgres. ``execute`` and
``scalars`` pull from one ordered queue. ``scalar`` and ``get`` pull from their own
queues. ``flush`` assigns ids and stands in for the DB ``gen_random_uuid()``. Every
audit write consumes two ``execute`` calls: the advisory lock and the ``prev_hash``
select. The tests size the queue for that.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeUpdate,
    FlowVersionCreate,
    GremiumCreate,
    GremiumMailRecipients,
    GremiumUpdate,
    GroupMappingCreate,
    GroupMappingUpdate,
    RoleAssignmentCreate,
    RoleAssignmentUpdate,
    RoleCreate,
    RoleUpdate,
    WebhookCreate,
    WebhookUpdate,
)
from app.modules.admin.service import ConfigService
from app.modules.admin.service.application_types import _type_out
from app.modules.admin.service.gremien import _gremium_out
from app.modules.admin.service.rbac import (
    _assignment_out,
    _mapping_out,
    _principal_out,
)
from app.modules.admin.service.service_base import _iso, _parse_dt
from app.modules.admin.service.webhooks import (
    _delivery_reason_class,
    _delivery_status_out,
    _webhook_out,
)
from app.shared.config_schemas import ComparisonOffers, FlowGraph
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ValidationProblem,
)


class FakeResult:
    """Stand-in for ``Result`` in ``execute`` and ``scalars`` with just enough methods."""

    def __init__(self, items: Iterable[Any] = ()) -> None:
        self._items = list(items)

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def scalar_one(self) -> Any:
        return self._items[0]

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None


def res(*items: Any) -> FakeResult:
    return FakeResult(items)


class FakeSession:
    """Stub for ``AsyncSession``.

    ``execute`` **and** ``scalars`` pull from the same ordered queue ``_results``, because
    the service calls them in a nested way. ``scalar`` pulls from its own queue
    ``_scalars`` and ``get`` pulls from its own queue ``_gets``. Both default to ``None``.
    ``flush`` gives an id to every added object that still has none.
    """

    def __init__(
        self,
        results: Iterable[FakeResult] = (),
        *,
        scalars: Iterable[Any] = (),
        gets: Iterable[Any] = (),
    ) -> None:
        self._results = list(results)
        self._scalars = list(scalars)
        self._gets = list(gets)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.statements: list[Any] = []
        self.flushed = 0
        self.committed = 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        return self._results.pop(0) if self._results else FakeResult()

    async def scalars(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        return self._results.pop(0) if self._results else FakeResult()

    async def scalar(self, stmt: Any) -> Any:
        self.statements.append(stmt)
        return self._scalars.pop(0) if self._scalars else None

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self._gets.pop(0) if self._gets else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed += 1


# Every audit write consumes two ``execute`` results: the ``pg_advisory_xact_lock``
# and the ``prev_hash`` select.
def audit_results() -> list[FakeResult]:
    return [res(), res()]


def svc(
    results: Iterable[FakeResult] = (),
    *,
    scalars: Iterable[Any] = (),
    gets: Iterable[Any] = (),
) -> tuple[ConfigService, FakeSession]:
    session = FakeSession(results, scalars=scalars, gets=gets)
    return ConfigService(session), session  # type: ignore[arg-type]


# The row doubles below carry no DB default, so each factory lists every column.
class Row:
    """Generic attribute container for ORM row doubles."""

    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


def gremium_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "name": "Gremium",
        "slug": "g",
        "cd_variant_id": None,
        "default_lang": "de",
        "allow_vote_delegation": False,
        "delegation_lead_minutes": 0,
        "delegation_allow_external": False,
        "quorum_percent": None,
    }
    base.update(kw)
    return Row(**base)


def type_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "gremium_id": None,
        "key": "antrag",
        "name_i18n": {"de": "Antrag"},
        "has_budget": False,
        "comparison_offers": None,
        "retention_months": None,
        "active_form_version_id": None,
    }
    base.update(kw)
    return Row(**base)


def role_row(**kw: Any) -> Any:
    base = {"id": uuid.uuid4(), "key": "editor", "name_i18n": {"de": "Editor"}}
    base.update(kw)
    return Row(**base)


def assignment_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "principal_id": uuid.uuid4(),
        "role_id": uuid.uuid4(),
        "gremium_id": None,
        "granted_by": "admin",
        "valid_from": None,
        "valid_until": None,
        "delegate_voting": False,
    }
    base.update(kw)
    return Row(**base)


def principal_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "sub": "user-sub",
        "email": "u@example.org",
        "display_name": "User",
        "last_login": None,
        "active": True,
    }
    base.update(kw)
    return Row(**base)


def mapping_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "oidc_group": "grp",
        "role_id": uuid.uuid4(),
        "gremium_id": None,
    }
    base.update(kw)
    return Row(**base)


def webhook_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "name": "hook",
        "url": "https://x.example/hook",
        "events": ["status_changed"],
        "active": True,
    }
    base.update(kw)
    return Row(**base)


def test_parse_dt_none() -> None:
    assert _parse_dt(None) is None


def test_parse_dt_naive_becomes_utc() -> None:
    # The parser reads a naive input as UTC and returns an aware value.
    assert _parse_dt("2026-06-07T10:00:00") == datetime(2026, 6, 7, 10, 0, tzinfo=UTC)


def test_parse_dt_aware_normalized_to_utc() -> None:
    assert _parse_dt("2026-06-07T12:00:00+02:00") == datetime(
        2026, 6, 7, 10, 0, tzinfo=UTC
    )


def test_parse_dt_invalid_raises_validation_problem() -> None:
    with pytest.raises(ValidationProblem) as ei:
        _parse_dt("not-a-date")
    assert ei.value.status == 422
    assert ei.value.errors is not None
    assert ei.value.errors[0].field == "validFrom/validUntil"


def test_iso_none_and_value() -> None:
    assert _iso(None) is None
    assert _iso(datetime(2026, 1, 2, tzinfo=UTC)) == "2026-01-02T00:00:00+00:00"


def test_mappers_roundtrip() -> None:
    g = _gremium_out(gremium_row(quorum_percent=50))
    assert g.quorum_percent == 50

    t = _type_out(type_row(comparison_offers={"required": True}))
    assert t.comparison_offers == {"required": True}

    a = _assignment_out(
        assignment_row(valid_from=datetime(2026, 1, 1, tzinfo=UTC))
    )
    assert a.valid_from == "2026-01-01T00:00:00+00:00"

    w = _webhook_out(webhook_row())
    assert w.events == ["status_changed"]

    m = _mapping_out(mapping_row())
    assert m.oidc_group == "grp"


def test_principal_out_active_none_defaults_true() -> None:
    # An active value of None means the default True (#legacy-row without a column value).
    out = _principal_out(principal_row(active=None), [])
    assert out.active is True
    # An explicit False stays False.
    out2 = _principal_out(principal_row(active=False), [])
    assert out2.active is False


async def test_list_gremien() -> None:
    s, _ = svc([res(gremium_row(name="A"), gremium_row(name="B"))])
    out = await s.list_gremien()
    assert len(out) == 2


async def test_create_gremium_ok() -> None:
    # Queue: _gremium_by_slug finds no row so the slug is free, ensure_forced_roles finds
    # no role, then the two audit results.
    s, sess = svc(
        [res(), res(), *audit_results()]
    )
    out = await s.create_gremium(
        GremiumCreate(name="Neu", slug="neu", quorumPercent=10), "admin"
    )
    assert out.name == "Neu"
    assert sess.committed == 1


async def test_create_gremium_slug_conflict() -> None:
    s, _ = svc([res(gremium_row(slug="dup"))])
    with pytest.raises(ConflictError):
        await s.create_gremium(GremiumCreate(name="X", slug="dup"), "admin")


async def test_update_gremium_all_fields() -> None:
    row = gremium_row(slug="old")
    # Queue: the row from get, a free slug from _gremium_by_slug, then two audit results.
    s, _ = svc([res(), *audit_results()], gets=[row])
    out = await s.update_gremium(
        row.id,
        GremiumUpdate(
            name="Neu",
            slug="neu",
            defaultLang="en",
            allowVoteDelegation=True,
            delegationLeadMinutes=5,
            delegationAllowExternal=True,
            quorumPercent=33,
        ),
        "admin",
    )
    assert out.name == "Neu"
    assert row.slug == "neu"
    assert row.quorum_percent == 33


async def test_update_gremium_quorum_set_to_null() -> None:
    row = gremium_row(quorum_percent=50)
    s, _ = svc([*audit_results()], gets=[row])
    # An explicit quorumPercent of None lands in model_fields_set, so the service sets None.
    out = await s.update_gremium(
        row.id, GremiumUpdate.model_validate({"quorumPercent": None}), "admin"
    )
    assert out.quorum_percent is None


async def test_update_gremium_noop_keeps_values() -> None:
    row = gremium_row(name="Bleibt", slug="same")
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_gremium(row.id, GremiumUpdate(), "admin")
    assert out.name == "Bleibt"


async def test_update_gremium_same_slug_no_conflict_check() -> None:
    # The slug equals row.slug, so the service runs NO _gremium_by_slug query.
    row = gremium_row(slug="keep")
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_gremium(row.id, GremiumUpdate(slug="keep"), "admin")
    assert out.slug == "keep"


async def test_update_gremium_slug_conflict() -> None:
    row = gremium_row(slug="old")
    s, _ = svc([res(gremium_row(slug="taken"))], gets=[row])
    with pytest.raises(ConflictError):
        await s.update_gremium(row.id, GremiumUpdate(slug="taken"), "admin")


async def test_update_gremium_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.update_gremium(uuid.uuid4(), GremiumUpdate(name="x"), "admin")


async def test_delete_gremium_ok() -> None:
    row = gremium_row()
    s, sess = svc([*audit_results()], gets=[row])
    await s.delete_gremium(row.id, "admin")
    assert row in sess.deleted
    assert sess.committed == 1


async def test_delete_gremium_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.delete_gremium(uuid.uuid4(), "admin")


async def test_get_gremium_mail_recipients_union_dedup() -> None:
    gid = uuid.uuid4()
    # Queue: get returns the Gremium, then the recipient lists. One row is ``None``, which
    # covers the ``recipients or []`` branch. One address appears twice.
    s, _ = svc(
        [res(["a@x.de", "b@x.de"], ["b@x.de"], None)],
        gets=[gremium_row(id=gid)],
    )
    out = await s.get_gremium_mail_recipients(gid)
    assert out.recipients == ["a@x.de", "b@x.de"]


async def test_get_gremium_mail_recipients_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.get_gremium_mail_recipients(uuid.uuid4())


async def test_set_gremium_mail_recipients_with_addresses() -> None:
    gid = uuid.uuid4()
    # Queue: the Gremium from get, the delete execute, then the two audit results.
    s, sess = svc([res(), *audit_results()], gets=[gremium_row(id=gid)])
    out = await s.set_gremium_mail_recipients(
        gid, GremiumMailRecipients(recipients=["a@x.de"]), "admin"
    )
    assert out.recipients == ["a@x.de"]
    # The service adds one MailList row next to the audit row.
    assert sum(type(o).__name__ == "MailList" for o in sess.added) == 1


async def test_set_gremium_mail_recipients_empty_adds_nothing() -> None:
    gid = uuid.uuid4()
    s, sess = svc([res(), *audit_results()], gets=[gremium_row(id=gid)])
    out = await s.set_gremium_mail_recipients(
        gid, GremiumMailRecipients(recipients=[]), "admin"
    )
    assert out.recipients == []
    # No MailList row, only the audit row.
    assert sum(type(o).__name__ == "MailList" for o in sess.added) == 0


async def test_set_gremium_mail_recipients_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.set_gremium_mail_recipients(
            uuid.uuid4(), GremiumMailRecipients(recipients=[]), "admin"
        )


async def test_list_application_types() -> None:
    s, _ = svc([res(type_row(), type_row(key="b"))])
    out = await s.list_application_types()
    assert len(out) == 2


async def test_create_application_type_with_comparison_offers() -> None:
    # Queue: the existing-type select returns None, then the two audit results.
    s, sess = svc([res(), *audit_results()])
    out = await s.create_application_type(
        ApplicationTypeCreate(
            key="neu",
            nameI18n={"de": "Neu"},
            comparisonOffers=ComparisonOffers(required=True),
            retentionMonths=12,
        ),
        "admin",
    )
    assert out.key == "neu"
    assert out.comparison_offers is not None
    assert out.comparison_offers["required"] is True
    assert sess.committed == 1


async def test_create_application_type_without_comparison_offers() -> None:
    s, _ = svc([res(), *audit_results()])
    out = await s.create_application_type(
        ApplicationTypeCreate(key="plain", nameI18n={"de": "P"}), "admin"
    )
    assert out.comparison_offers is None


async def test_create_application_type_conflict() -> None:
    s, _ = svc([res(type_row(key="dup"))])
    with pytest.raises(ConflictError):
        await s.create_application_type(
            ApplicationTypeCreate(key="dup", nameI18n={"de": "x"}), "admin"
        )


async def test_update_application_type_all_fields() -> None:
    row = type_row()
    gid = uuid.uuid4()
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_application_type(
        row.id,
        ApplicationTypeUpdate(
            nameI18n={"de": "Neu"},
            gremiumId=gid,
            hasBudget=True,
            comparisonOffers=ComparisonOffers(required=True),
            retentionMonths=6,
        ),
        "admin",
    )
    assert out.name_i18n == {"de": "Neu"}
    assert row.gremium_id == gid
    assert row.has_budget is True
    assert row.retention_months == 6
    assert row.comparison_offers == {
        "required": True,
        "minCount": 2,
        "thresholdAmount": None,
        "as": "file",
    }


async def test_update_application_type_retention_set_null() -> None:
    row = type_row(retention_months=12)
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_application_type(
        row.id, ApplicationTypeUpdate.model_validate({"retentionMonths": None}), "admin"
    )
    assert out.retention_months is None


async def test_update_application_type_noop() -> None:
    row = type_row(name_i18n={"de": "Bleibt"})
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_application_type(row.id, ApplicationTypeUpdate(), "admin")
    assert out.name_i18n == {"de": "Bleibt"}


async def test_update_application_type_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.update_application_type(
            uuid.uuid4(), ApplicationTypeUpdate(hasBudget=True), "admin"
        )


async def test_delete_application_type_ok() -> None:
    row = type_row()
    # Queue: the type row from get, in_use None from scalar, then two audit results.
    s, sess = svc([*audit_results()], scalars=[None], gets=[row])
    await s.delete_application_type(row.id, "admin")
    assert row in sess.deleted
    assert sess.committed == 1


async def test_delete_application_type_in_use_conflict() -> None:
    row = type_row()
    s, _ = svc(scalars=[uuid.uuid4()], gets=[row])
    with pytest.raises(ConflictError):
        await s.delete_application_type(row.id, "admin")


async def test_delete_application_type_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.delete_application_type(uuid.uuid4(), "admin")


def _flow_state_row(key: str, **kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "key": key,
        "label_i18n": {"de": key},
        "color": None,
        "edit_allowed": True,
        "is_initial": False,
        "is_terminal": False,
        "kind": "normal",
        "config": {},
        "flow_version_id": uuid.uuid4(),
    }
    base.update(kw)
    return Row(**base)


def _flow_transition_row(from_id: Any, to_id: Any, **kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "from_state_id": from_id,
        "to_state_id": to_id,
        "label_i18n": {},
        "color": None,
        "guard": None,
        "actions": [],
        "order": 0,
        "automatic": False,
        "branch": None,
        "requires_action": True,
    }
    base.update(kw)
    return Row(**base)


def _flow_version_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "version": 1,
        "active": True,
        "editor_layout": {},
    }
    base.update(kw)
    return Row(**base)


async def test_get_active_global_flow_none() -> None:
    s, _ = svc(scalars=[None])
    assert await s.get_active_global_flow() is None


async def test_get_active_global_flow_returns_graph() -> None:
    version = _flow_version_row(editor_layout={"x": 1})
    s_init = _flow_state_row("draft", is_initial=True)
    s_done = _flow_state_row("done", is_terminal=True, color="#0f0")
    trans = _flow_transition_row(
        s_init.id,
        s_done.id,
        label_i18n={"de": "fertig"},
        actions=[{"type": "notify"}],
    )
    # Queue: the version, the states, then the transitions.
    s, _ = svc(
        [res(s_init, s_done), res(trans)],
        scalars=[version],
    )
    graph = await s.get_active_global_flow()
    assert graph is not None
    assert {st.key for st in graph.states} == {"draft", "done"}
    assert graph.transitions[0].from_ == "draft"
    assert graph.transitions[0].to == "done"
    assert graph.layout == {"x": 1}


async def test_get_active_global_flow_empty_label_and_layout() -> None:
    version = _flow_version_row(editor_layout={})
    s_init = _flow_state_row("draft", is_initial=True)
    s_done = _flow_state_row("done")
    # An empty label_i18n and actions None give label None and an empty actions list.
    trans = _flow_transition_row(s_init.id, s_done.id, label_i18n="", actions=None)
    s, _ = svc([res(s_init, s_done), res(trans)], scalars=[version])
    graph = await s.get_active_global_flow()
    assert graph is not None
    assert graph.transitions[0].label is None
    assert graph.transitions[0].actions == []
    assert graph.layout is None


def _two_state_graph() -> FlowGraph:
    return FlowGraph.model_validate(
        {
            "states": [
                {"key": "draft", "label": {"de": "Entwurf"}, "isInitial": True},
                {"key": "done", "label": {"de": "Fertig"}, "isTerminal": True},
            ],
            "transitions": [
                {"from": "draft", "to": "done", "label": {"de": "ab"}},
            ],
            "layout": {"draft": {"x": 1}},
        }
    )


async def test_create_global_flow_version_fresh_no_existing_version() -> None:
    """With no FlowVersion yet the service creates the version, the states and the graph."""
    graph = _two_state_graph()
    # execute order:
    #  1 app_keys select.all() -> no applications
    #  2 select FlowVersion .scalar_one_or_none() -> None, so the service creates one
    #  3 update FlowVersion (deactivate the others)
    #  4 select existing State .scalars().all() -> none, because the flow is fresh
    #  5 select Transition.id .scalars().all() -> none
    #  6 update Application where current_state_id is None
    #  7,8 audit
    s, sess = svc(
        [res(), res(), res(), res(), res(), res(), *audit_results()]
    )
    out = await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    assert out.active is True
    assert out.version == 1
    assert sess.committed == 1
    added_types = [type(o).__name__ for o in sess.added]
    assert "FlowVersion" in added_types
    assert added_types.count("State") == 2
    assert added_types.count("Transition") == 1


async def test_create_global_flow_version_new_version_remaps_apps() -> None:
    """A save creates a NEW immutable FlowVersion.

    The service moves a running application to the newest version by state key. A removed
    key falls back to the initial state. The service writes fresh state and transition
    rows and deletes **no** old version.

    DB queue: ``app_keys`` (execute) returns one application on the removed key
    ``legacy``. ``max_version`` (scalar) is 3, so the new version is 4. Every other
    execute call falls back to the empty default result: deactivate, the per-application
    update, the None update and the config_revision record. ``head`` (scalar) is None.
    """
    graph = _two_state_graph()
    app_id = uuid.uuid4()
    s, sess = svc([res((app_id, "legacy"))], scalars=[3])
    out = await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    assert out.version == 4
    assert out.active is True
    added_types = [type(o).__name__ for o in sess.added]
    assert added_types.count("FlowVersion") == 1
    # Fresh states without reuse of an old version, plus the transition.
    assert added_types.count("State") == 2
    assert added_types.count("Transition") == 1
    # Append-only: the service deletes nothing, so the earlier version survives.
    assert sess.deleted == []
    assert sess.committed == 1


async def test_create_global_flow_version_no_apps_bumps_version() -> None:
    """Without running applications the new version is ``max+1``.

    The bulk update for ``current_state_id IS NULL`` runs and the service deletes nothing.
    """
    graph = _two_state_graph()
    s, sess = svc([res()], scalars=[5])  # no applications, max 5, so the new version is 6
    out = await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    assert out.version == 6
    assert out.active is True
    assert sess.deleted == []
    assert sess.committed == 1


async def test_create_global_flow_version_transition_explicit_order() -> None:
    """A set ``trans.order`` reaches the row (the branch order is not None)."""
    graph = FlowGraph.model_validate(
        {
            "states": [
                {"key": "draft", "label": {"de": "E"}, "isInitial": True},
                {"key": "done", "label": {"de": "F"}},
            ],
            "transitions": [
                {"from": "draft", "to": "done", "order": 7},
            ],
        }
    )
    s, sess = svc([res(), res(), res(), res(), res(), res(), *audit_results()])
    await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    trans_objs = [o for o in sess.added if type(o).__name__ == "Transition"]
    assert trans_objs[0].order == 7


async def test_create_global_flow_version_invalid_graph_422() -> None:
    # Without an initial state the service raises ValidationProblem before any DB access.
    graph = FlowGraph.model_validate(
        {"states": [{"key": "a", "label": {"de": "A"}}], "transitions": []}
    )
    s, _ = svc()
    with pytest.raises(ValidationProblem) as ei:
        await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    assert ei.value.status == 422


async def test_list_roles_groups_permissions() -> None:
    r1 = role_row(key="a")
    r2 = role_row(key="b")
    perm = Row(role_id=r1.id, permission="x.read")
    perm2 = Row(role_id=r1.id, permission="x.write")
    # Queue: the roles, then the permissions.
    s, _ = svc([res(r1, r2), res(perm, perm2)])
    out = await s.list_roles()
    by_key = {o.key: o for o in out}
    assert by_key["a"].permissions == ["x.read", "x.write"]
    assert by_key["b"].permissions == []


async def test_create_role_ok() -> None:
    # Queue: the existing-role select returns None, then the two audit results.
    s, sess = svc([res(), *audit_results()])
    out = await s.create_role(
        RoleCreate(
            key="neu",
            label={"de": "Neu"},
            permissions=["application.read", "application.read"],
        ),
        "admin",
    )
    assert out.key == "neu"
    assert out.permissions == ["application.read"]
    # One RolePermission row, because the service drops the duplicate.
    assert sum(type(o).__name__ == "RolePermission" for o in sess.added) == 1


async def test_create_role_conflict() -> None:
    s, _ = svc([res(role_row(key="dup"))])
    with pytest.raises(ConflictError):
        await s.create_role(RoleCreate(key="dup"), "admin")


async def test_update_role_label_and_permissions() -> None:
    role = role_row()
    # Queue: the role, the permission delete, two audit results, the permissions after.
    s, _ = svc(
        [res(), *audit_results(), res("application.read", "application.create")],
        gets=[role],
    )
    out = await s.update_role(
        role.id,
        RoleUpdate(
            label={"de": "Neu"},
            permissions=["application.read", "application.create"],
        ),
        "admin",
    )
    assert role.name_i18n == {"de": "Neu"}
    assert out.permissions == ["application.create", "application.read"]


async def test_update_role_permissions_only_label_none() -> None:
    # A None label skips the branch 572->574. The payload sets the permissions.
    role = role_row(name_i18n={"de": "Alt"})
    s, _ = svc(
        [res(), *audit_results(), res("application.create")],
        gets=[role],
    )
    out = await s.update_role(
        role.id, RoleUpdate(permissions=["application.create"]), "admin"
    )
    assert role.name_i18n == {"de": "Alt"}  # unchanged
    assert out.permissions == ["application.create"]


async def test_update_role_no_permissions_change() -> None:
    role = role_row()
    # A None permissions field skips the delete. Queue: two audit results, then no row.
    s, _ = svc([*audit_results(), res()], gets=[role])
    out = await s.update_role(role.id, RoleUpdate(label={"de": "Nur Label"}), "admin")
    assert out.label == {"de": "Nur Label"}
    assert out.permissions == []


async def test_update_role_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.update_role(uuid.uuid4(), RoleUpdate(label={"de": "x"}), "admin")


async def test_delete_role_ok() -> None:
    role = role_row(key="editor")
    s, sess = svc([*audit_results()], gets=[role])
    await s.delete_role(role.id, "admin")
    assert role in sess.deleted


async def test_delete_role_protected() -> None:
    for key in ("admin", "member"):
        role = role_row(key=key)
        s, _ = svc(gets=[role])
        with pytest.raises(ConflictError):
            await s.delete_role(role.id, "admin")


async def test_delete_role_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.delete_role(uuid.uuid4(), "admin")


async def test_list_role_assignments() -> None:
    s, _ = svc([res(assignment_row(), assignment_row())])
    out = await s.list_role_assignments()
    assert len(out) == 2


async def test_create_role_assignment_ok() -> None:
    principal = principal_row()
    role = role_row()
    # Queue: the principal, the role, then the two audit results.
    s, sess = svc([*audit_results()], gets=[principal, role])
    out = await s.create_role_assignment(
        RoleAssignmentCreate(
            principalId=principal.id,
            roleId=role.id,
            validFrom="2026-01-01T00:00:00Z",
            validUntil="2026-12-31T00:00:00Z",
            delegateVoting=True,
        ),
        "admin",
    )
    assert out.delegate_voting is True
    assert out.valid_from == "2026-01-01T00:00:00+00:00"
    assert sess.committed == 1


async def test_create_role_assignment_principal_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.create_role_assignment(
            RoleAssignmentCreate(principalId=uuid.uuid4(), roleId=uuid.uuid4()), "admin"
        )


async def test_create_role_assignment_role_not_found() -> None:
    principal = principal_row()
    s, _ = svc(gets=[principal, None])
    with pytest.raises(NotFoundError):
        await s.create_role_assignment(
            RoleAssignmentCreate(principalId=principal.id, roleId=uuid.uuid4()), "admin"
        )


async def test_update_role_assignment_all_fields_non_admin_role() -> None:
    row = assignment_row()
    new_role = role_row(key="editor")
    new_role_id = new_role.id
    old_role = role_row(key="editor")  # _guard_self_admin_removal: not admin
    gid = uuid.uuid4()
    # Queue: the assignment row, the new role for the existence check, the old role for
    # the guard, then the two audit results.
    s, _ = svc([*audit_results()], gets=[row, new_role, old_role])
    out = await s.update_role_assignment(
        row.id,
        RoleAssignmentUpdate(
            roleId=new_role_id,
            gremiumId=gid,
            validFrom="2026-02-01T00:00:00Z",
            validUntil="2026-03-01T00:00:00Z",
            delegateVoting=True,
        ),
        "admin",
    )
    assert row.role_id == new_role_id
    assert row.gremium_id == gid
    assert out.delegate_voting is True


async def test_update_role_assignment_same_role_guard_runs_non_admin() -> None:
    # AUD-031: _guard_self_admin_removal now ALWAYS runs first. For a non-admin role
    # (editor) the guard returns without a conflict.
    # gets: the assignment row, the editor role for the guard, the role for the
    # existence check.
    rid = uuid.uuid4()
    row = assignment_row(role_id=rid)
    editor_role = role_row(id=rid)
    s, _ = svc([*audit_results()], gets=[row, editor_role, editor_role])
    out = await s.update_role_assignment(
        row.id, RoleAssignmentUpdate(roleId=rid), "admin"
    )
    assert out.role_id == rid


async def test_update_role_assignment_role_not_found() -> None:
    row = assignment_row()
    s, _ = svc(gets=[row, None])
    with pytest.raises(NotFoundError):
        await s.update_role_assignment(
            row.id, RoleAssignmentUpdate(roleId=uuid.uuid4()), "admin"
        )


async def test_update_role_assignment_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.update_role_assignment(
            uuid.uuid4(), RoleAssignmentUpdate(delegateVoting=True), "admin"
        )


async def test_update_role_assignment_self_admin_removal_blocked() -> None:
    # The row holds the admin role and principal.sub equals the actor. The role change
    # therefore raises ConflictError.
    principal = principal_row(sub="me")
    row = assignment_row(principal_id=principal.id)
    new_role = role_row(key="editor")
    admin_role = role_row(key="admin")
    # AUD-031: the guard runs first. gets: the row, the admin role, the principal.
    s, _ = svc(gets=[row, admin_role, principal])
    with pytest.raises(ConflictError):
        await s.update_role_assignment(
            row.id, RoleAssignmentUpdate(roleId=new_role.id), "me"
        )


async def test_update_role_assignment_noop() -> None:
    row = assignment_row(delegate_voting=False)
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_role_assignment(row.id, RoleAssignmentUpdate(), "admin")
    assert out.delegate_voting is False


async def test_update_role_assignment_self_admin_valid_until_self_expiry_blocked() -> (
    None
):
    # AUD-031: a change that does not touch role_id (a past valid_until) on the OWN admin
    # assignment must fail. Otherwise the admin can expire the own access.
    principal = principal_row(sub="me")
    row = assignment_row(principal_id=principal.id)
    admin_role = role_row(key="admin")
    # gets: the row, the admin role, the principal.
    s, sess = svc(gets=[row, admin_role, principal])
    with pytest.raises(ConflictError):
        await s.update_role_assignment(
            row.id,
            RoleAssignmentUpdate(validUntil="2000-01-01T00:00:00Z"),
            "me",
        )
    assert sess.committed == 0
    assert row.valid_until is None  # unchanged


async def test_delete_role_assignment_ok() -> None:
    # gets: the assignment row, the editor role for the guard (not admin), the editor
    # role for the member check (the key is not member). Then the two audit results.
    row = assignment_row()
    guard_role = role_row(key="editor")
    member_role = role_row(key="editor")
    s, sess = svc([*audit_results()], gets=[row, guard_role, member_role])
    await s.delete_role_assignment(row.id, "admin")
    assert row in sess.deleted


async def test_delete_role_assignment_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.delete_role_assignment(uuid.uuid4(), "admin")


async def test_delete_role_assignment_member_unremovable() -> None:
    # gets: the assignment, a non-admin role for the guard, the member role. A member
    # role with gremium_id None raises ConflictError.
    row = assignment_row(gremium_id=None)
    guard_role = role_row(key="editor")
    member_role = role_row(key="member")
    s, _ = svc(gets=[row, guard_role, member_role])
    with pytest.raises(ConflictError):
        await s.delete_role_assignment(row.id, "admin")


async def test_delete_role_assignment_member_with_gremium_ok() -> None:
    # The member role with a set gremium_id stays deletable (branch gremium_id not None).
    row = assignment_row(gremium_id=uuid.uuid4())
    guard_role = role_row(key="editor")
    member_role = role_row(key="member")
    s, sess = svc([*audit_results()], gets=[row, guard_role, member_role])
    await s.delete_role_assignment(row.id, "admin")
    assert row in sess.deleted


async def test_delete_role_assignment_self_admin_blocked() -> None:
    principal = principal_row(sub="me")
    row = assignment_row(principal_id=principal.id)
    admin_role = role_row(key="admin")
    # gets: the assignment, the admin role for the guard, the principal. The sub equals
    # the actor, so the call raises ConflictError.
    s, _ = svc(gets=[row, admin_role, principal])
    with pytest.raises(ConflictError):
        await s.delete_role_assignment(row.id, "me")


async def test_guard_self_admin_role_none_returns() -> None:
    # _guard_self_admin_removal returns early when the role is None. No conflict.
    row = assignment_row()
    s, _ = svc(gets=[None])
    await s._guard_self_admin_removal(row, "anyone")  # must NOT raise


async def test_guard_self_admin_other_principal_ok() -> None:
    # The role is admin, but principal.sub differs from the actor, so no conflict.
    row = assignment_row()
    admin_role = role_row(key="admin")
    other = principal_row(sub="someone-else")
    s, _ = svc(gets=[admin_role, other])
    await s._guard_self_admin_removal(row, "actor-sub")


async def test_guard_self_admin_principal_none_ok() -> None:
    # The role is admin and the principal is None, so no conflict (branch principal None).
    row = assignment_row()
    admin_role = role_row(key="admin")
    s, _ = svc(gets=[admin_role, None])
    await s._guard_self_admin_removal(row, "actor")


async def test_search_principals_with_query_and_assignments() -> None:
    p1 = principal_row(sub="alice")
    p2 = principal_row(sub="bob")
    a1 = assignment_row(principal_id=p1.id)
    # Queue: the principals, then the assignments.
    s, _ = svc([res(p1, p2), res(a1)])
    out = await s.search_principals("ali")
    by_sub = {o.sub: o for o in out}
    assert len(by_sub["alice"].assignments) == 1
    assert by_sub["bob"].assignments == []


async def test_search_principals_no_query_no_results() -> None:
    # A None query adds no where clause. Without a principal the service skips the
    # assignments query.
    s, _ = svc([res()])
    out = await s.search_principals(None)
    assert out == []


async def test_set_principal_active_activate() -> None:
    principal = principal_row(active=False, sub="x")
    # Queue: the principal, the two audit results, then the assignments.
    s, _ = svc([*audit_results(), res()], gets=[principal])
    out = await s.set_principal_active(principal.id, True, "admin")
    assert out.active is True
    assert principal.active is True


async def test_set_principal_active_deactivate_other() -> None:
    principal = principal_row(active=True, sub="someone")
    s, _ = svc([*audit_results(), res(assignment_row(principal_id=principal.id))],
               gets=[principal])
    out = await s.set_principal_active(principal.id, False, "admin")
    assert out.active is False
    assert len(out.assignments) == 1


async def test_set_principal_active_self_deactivate_blocked() -> None:
    principal = principal_row(active=True, sub="me")
    s, _ = svc(gets=[principal])
    with pytest.raises(ConflictError):
        await s.set_principal_active(principal.id, False, "me")


async def test_set_principal_active_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.set_principal_active(uuid.uuid4(), True, "admin")


def test_list_permissions() -> None:
    s, _ = svc()
    perms = s.list_permissions()
    assert isinstance(perms, list)
    assert all(isinstance(p, str) for p in perms)
    assert len(perms) > 0


async def test_list_group_mappings() -> None:
    s, _ = svc([res(mapping_row(), mapping_row())])
    out = await s.list_group_mappings()
    assert len(out) == 2


async def test_create_group_mapping_ok() -> None:
    role = role_row()
    # Queue: the role, then the two audit results.
    s, sess = svc([*audit_results()], gets=[role])
    out = await s.create_group_mapping(
        GroupMappingCreate(oidcGroup="grp", roleId=role.id), "admin"
    )
    assert out.oidc_group == "grp"
    assert sess.committed == 1


async def test_create_group_mapping_role_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.create_group_mapping(
            GroupMappingCreate(oidcGroup="g", roleId=uuid.uuid4()), "admin"
        )


async def test_update_group_mapping_all_fields() -> None:
    row = mapping_row()
    new_role = role_row()
    gid = uuid.uuid4()
    # Queue: the mapping row, the role for the existence check, then two audit results.
    s, _ = svc([*audit_results()], gets=[row, new_role])
    out = await s.update_group_mapping(
        row.id,
        GroupMappingUpdate(oidcGroup="neu", roleId=new_role.id, gremiumId=gid),
        "admin",
    )
    assert row.oidc_group == "neu"
    assert row.role_id == new_role.id
    assert row.gremium_id == gid
    assert out.oidc_group == "neu"


async def test_update_group_mapping_noop() -> None:
    row = mapping_row(oidc_group="bleibt")
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_group_mapping(row.id, GroupMappingUpdate(), "admin")
    assert out.oidc_group == "bleibt"


async def test_update_group_mapping_role_not_found() -> None:
    row = mapping_row()
    s, _ = svc(gets=[row, None])
    with pytest.raises(NotFoundError):
        await s.update_group_mapping(
            row.id, GroupMappingUpdate(roleId=uuid.uuid4()), "admin"
        )


async def test_update_group_mapping_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.update_group_mapping(
            uuid.uuid4(), GroupMappingUpdate(oidcGroup="x"), "admin"
        )


async def test_delete_group_mapping_ok() -> None:
    row = mapping_row()
    s, sess = svc([*audit_results()], gets=[row])
    await s.delete_group_mapping(row.id, "admin")
    assert row in sess.deleted


async def test_delete_group_mapping_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.delete_group_mapping(uuid.uuid4(), "admin")


async def test_list_webhooks() -> None:
    s, _ = svc([res(webhook_row(), webhook_row(name="b"))])
    out = await s.list_webhooks()
    assert len(out) == 2


async def test_create_webhook_ok() -> None:
    s, sess = svc([*audit_results()])
    out = await s.create_webhook(
        WebhookCreate(
            name="hook", url="https://x.example/h", events=["status_changed"]
        ),
        "admin",
    )
    assert out.name == "hook"
    assert out.events == ["status_changed"]
    # The server generates the secret with 32 bytes.
    wh = sess.added[0]
    assert isinstance(wh.secret, bytes)
    assert len(wh.secret) == 32


async def test_update_webhook_all_fields() -> None:
    row = webhook_row()
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_webhook(
        row.id,
        WebhookUpdate(
            name="neu",
            url="https://y.example/h",
            events=["vote_opened"],
            active=False,
        ),
        "admin",
    )
    assert row.name == "neu"
    assert row.url == "https://y.example/h"
    assert row.events == ["vote_opened"]
    assert row.active is False
    assert out.active is False


async def test_update_webhook_noop() -> None:
    row = webhook_row(name="bleibt")
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.update_webhook(row.id, WebhookUpdate(), "admin")
    assert out.name == "bleibt"


async def test_update_webhook_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.update_webhook(uuid.uuid4(), WebhookUpdate(name="x"), "admin")


async def test_delete_webhook_ok() -> None:
    row = webhook_row()
    s, session = svc([*audit_results()], gets=[row])
    await s.delete_webhook(row.id, "admin")
    assert session.deleted == [row]
    assert session.committed == 1


async def test_delete_webhook_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.delete_webhook(uuid.uuid4(), "admin")


# AUD-062: the advisory SSRF check of the webhook URL at CRUD time.
def test_webhook_url_advisory_blocks_internal_ip_literal() -> None:
    # The link-local metadata IP is not global, so this is a 400 and no silent dead-letter.
    with pytest.raises(BadRequestError):
        ConfigService._assert_webhook_url_advisory("http://169.254.169.254/")


def test_webhook_url_advisory_blocks_private_ip_literal() -> None:
    with pytest.raises(BadRequestError):
        ConfigService._assert_webhook_url_advisory("http://10.0.0.1/hook")


def test_webhook_url_advisory_blocks_bad_scheme() -> None:
    with pytest.raises(BadRequestError):
        ConfigService._assert_webhook_url_advisory("ftp://example.com/")


def test_webhook_url_advisory_allows_global_ip_literal() -> None:
    # A global IP literal passes without a block and without DNS.
    ConfigService._assert_webhook_url_advisory("https://1.1.1.1/hook")


def test_webhook_url_advisory_dns_failure_is_non_blocking() -> None:
    # The host does not resolve (.example is reserved), so the check stays best-effort.
    ConfigService._assert_webhook_url_advisory("https://x.example/h")


# AUD-062 (second half): the delivery-status diagnostic read.
def delivery_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "webhook_id": uuid.uuid4(),
        "status": "pending",
        "response_code": None,
        "attempts": 0,
        "last_at": None,
    }
    base.update(kw)
    return Row(**base)


def test_reason_class_buckets() -> None:
    # ok maps to delivered. pending maps to in_progress.
    assert _delivery_reason_class("ok", 200) == "delivered"
    assert _delivery_reason_class("pending", None) == "in_progress"
    # dead without an HTTP code (an SSRF block or a transport or DNS error) maps to
    # unreachable_or_blocked and never names the blocked IP.
    assert _delivery_reason_class("dead", None) == "unreachable_or_blocked"
    # failed with a running retry and without a code is a transient transport error.
    assert _delivery_reason_class("failed", None) == "transient_transport_error"
    # 4xx means the target rejects the call. 5xx means a target server error.
    assert _delivery_reason_class("dead", 404) == "rejected_by_target"
    assert _delivery_reason_class("dead", 503) == "target_server_error"


def test_delivery_status_out_never_when_no_delivery() -> None:
    wid = uuid.uuid4()
    out = _delivery_status_out(wid, None)
    assert out.webhook_id == wid
    assert out.last_state == "never"
    assert out.reason_class == "no_deliveries"
    assert out.response_code is None


def test_delivery_status_out_dead_no_ip_leak() -> None:
    # A mistyped or internal webhook ends as dead without an HTTP code. The view names
    # ONLY the coarse class, never a resolved IP and never a host.
    row = delivery_row(status="dead", response_code=None, attempts=5)
    out = _delivery_status_out(row.webhook_id, row)
    assert out.last_state == "dead"
    assert out.reason_class == "unreachable_or_blocked"
    assert out.attempts == 5
    # The diagnostic DTO carries no IP, host or body field.
    dumped = out.model_dump()
    assert "ip" not in dumped
    assert "host" not in dumped
    assert "url" not in dumped


def test_delivery_status_out_sent_maps_ok() -> None:
    moment = datetime(2026, 6, 21, tzinfo=UTC)
    row = delivery_row(status="ok", response_code=200, attempts=1, last_at=moment)
    out = _delivery_status_out(row.webhook_id, row)
    assert out.last_state == "sent"
    assert out.reason_class == "delivered"
    assert out.response_code == 200
    assert out.last_at == moment.isoformat()


async def test_list_webhook_delivery_status_per_hook() -> None:
    hook_a = webhook_row(name="a")
    hook_b = webhook_row(name="b")
    # The webhook list comes from the scalars queue (_results). Each hook gets one latest
    # delivery from the scalar queue (_scalars), in the same order.
    latest_a = delivery_row(webhook_id=hook_a.id, status="dead", response_code=None)
    s, _ = svc(
        [res(hook_a, hook_b)],
        scalars=[latest_a, None],
    )
    out = await s.list_webhook_delivery_status()
    assert len(out) == 2
    assert out[0].webhook_id == hook_a.id
    assert out[0].last_state == "dead"
    assert out[0].reason_class == "unreachable_or_blocked"
    # A hook without a delivery maps to never.
    assert out[1].webhook_id == hook_b.id
    assert out[1].last_state == "never"


# AUD-053: the role permission whitelist validation.
def test_role_create_rejects_unknown_permission() -> None:
    with pytest.raises(ValueError, match="unknown permission"):
        RoleCreate(key="r", permissions=["application.read", "bogus.key"])


def test_role_create_accepts_known_and_dedups() -> None:
    role = RoleCreate(
        key="r",
        permissions=["application.read", "application.read", "application.create"],
    )
    assert role.permissions == ["application.read", "application.create"]


def test_role_update_rejects_unknown_permission() -> None:
    with pytest.raises(ValueError, match="unknown permission"):
        RoleUpdate(permissions=["does.not.exist"])


def test_role_update_none_permissions_ok() -> None:
    assert RoleUpdate(permissions=None).permissions is None
