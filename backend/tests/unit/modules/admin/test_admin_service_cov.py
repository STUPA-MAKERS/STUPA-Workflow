"""DB-lose Voll-Coverage für ``ConfigService`` (app/modules/admin/service.py).

Treibt jeden CRUD-Pfad (Gremium / Application-Type / globaler Flow / Rollen /
Assignments / Principals / Group-Mappings / Webhooks) sowie alle Mapper und die
Guard-/Conflict-/NotFound-Zweige.

Es wird ein eigener ``AsyncSession``-Fake verwendet (kein Docker/Redis/Postgres):
``execute``/``scalars`` ziehen aus einer geordneten Queue, ``scalar``/``get`` aus
je eigenen Queues. ``flush`` vergibt IDs (DB-``gen_random_uuid()``-Ersatz). Jeder
Audit-Schreibvorgang verbraucht intern zwei ``execute``-Aufrufe (Advisory-Lock +
``prev_hash``-Select); die Tests legen die Queue entsprechend an.
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
from app.modules.admin.service import (
    ConfigService,
    _assignment_out,
    _delivery_reason_class,
    _delivery_status_out,
    _gremium_out,
    _iso,
    _mapping_out,
    _parse_dt,
    _principal_out,
    _type_out,
    _webhook_out,
)
from app.shared.config_schemas import ComparisonOffers, FlowGraph
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ValidationProblem,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeResult:
    """`Result`-Ersatz für ``execute``/``scalars`` (genug Methoden für den Service)."""

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
    """`AsyncSession`-Stub.

    * ``execute`` **und** ``scalars`` ziehen aus derselben geordneten Queue
      ``_results`` (so wie der Service sie verschachtelt aufruft).
    * ``scalar`` zieht aus ``_scalars`` (eigene Queue, Default ``None``).
    * ``get`` zieht aus ``_gets`` (eigene Queue, Default ``None``).
    * ``flush`` vergibt IDs an frisch hinzugefügte Objekte ohne ``id``.
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


# Jeder Audit-Schreibvorgang verbraucht intern zwei ``execute``-Ergebnisse
# (``pg_advisory_xact_lock`` + ``prev_hash``-Select). Als Bequemlichkeit:
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


# --------------------------------------------------------------------------- #
# Test-Doubles für ORM-Rows (leichtgewichtig, keine DB-Defaults)
# --------------------------------------------------------------------------- #
class Row:
    """Generischer Attribut-Container für ORM-Row-Doubles."""

    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


def gremium_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "name": "Gremium",
        "slug": "g",
        "cd_variant": "stupa",
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


# --------------------------------------------------------------------------- #
# _parse_dt / _iso (Modul-Helfer)
# --------------------------------------------------------------------------- #
def test_parse_dt_none() -> None:
    assert _parse_dt(None) is None


def test_parse_dt_naive_becomes_utc() -> None:
    # naive Eingabe → als UTC interpretiert (aware)
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


# --------------------------------------------------------------------------- #
# Mapper-Helfer
# --------------------------------------------------------------------------- #
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
    # active=None ⇒ True-Default (#legacy-row ohne Spaltenwert).
    out = _principal_out(principal_row(active=None), [])
    assert out.active is True
    # explizit False bleibt False
    out2 = _principal_out(principal_row(active=False), [])
    assert out2.active is False


# --------------------------------------------------------------------------- #
# Gremium
# --------------------------------------------------------------------------- #
async def test_list_gremien() -> None:
    s, _ = svc([res(gremium_row(name="A"), gremium_row(name="B"))])
    out = await s.list_gremien()
    assert len(out) == 2


async def test_create_gremium_ok() -> None:
    # _gremium_by_slug → None (frei); ensure_forced_roles select (keine) ; audit (2)
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
    # get(row); _gremium_by_slug(None=frei); audit(2)
    s, _ = svc([res(), *audit_results()], gets=[row])
    out = await s.update_gremium(
        row.id,
        GremiumUpdate(
            name="Neu",
            slug="neu",
            cdVariant="asta",
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
    # quorumPercent explizit None → in model_fields_set, also auf None gesetzt
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
    # slug == row.slug → KEIN _gremium_by_slug-Query (Branch: gleich)
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


# ------------------------------------------------- Protokoll-Verteiler
async def test_get_gremium_mail_recipients_union_dedup() -> None:
    gid = uuid.uuid4()
    # get(gremium present) ; scalars(recipients-listen). Eine Zeile ist ``None``
    # (deckt den ``recipients or []``-Zweig ab), eine Adresse kommt doppelt vor.
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
    # get(present) ; execute(delete) ; audit(2)
    s, sess = svc([res(), *audit_results()], gets=[gremium_row(id=gid)])
    out = await s.set_gremium_mail_recipients(
        gid, GremiumMailRecipients(recipients=["a@x.de"]), "admin"
    )
    assert out.recipients == ["a@x.de"]
    # eine MailList-Zeile wurde hinzugefügt (neben dem Audit-Eintrag)
    assert sum(type(o).__name__ == "MailList" for o in sess.added) == 1


async def test_set_gremium_mail_recipients_empty_adds_nothing() -> None:
    gid = uuid.uuid4()
    s, sess = svc([res(), *audit_results()], gets=[gremium_row(id=gid)])
    out = await s.set_gremium_mail_recipients(
        gid, GremiumMailRecipients(recipients=[]), "admin"
    )
    assert out.recipients == []
    # keine MailList-Zeile (nur der Audit-Eintrag)
    assert sum(type(o).__name__ == "MailList" for o in sess.added) == 0


async def test_set_gremium_mail_recipients_not_found() -> None:
    s, _ = svc(gets=[None])
    with pytest.raises(NotFoundError):
        await s.set_gremium_mail_recipients(
            uuid.uuid4(), GremiumMailRecipients(recipients=[]), "admin"
        )


# --------------------------------------------------------------------------- #
# Application-Type
# --------------------------------------------------------------------------- #
async def test_list_application_types() -> None:
    s, _ = svc([res(type_row(), type_row(key="b"))])
    out = await s.list_application_types()
    assert len(out) == 2


async def test_create_application_type_with_comparison_offers() -> None:
    # select(existing) None ; audit(2)
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
    # _get_type get(row) ; scalar(in_use None) ; audit(2)
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


# --------------------------------------------------------------------------- #
# Globaler Flow
# --------------------------------------------------------------------------- #
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
    # scalar(version) ; scalars(states) ; scalars(transitions)
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
    # transition mit leerem label_i18n und actions=None → label None, actions []
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
    """Kein bestehender FlowVersion ⇒ neu anlegen, States anlegen, Transitions bauen."""
    graph = _two_state_graph()
    # execute order:
    #  1 app_keys select.all() -> keine Anträge
    #  2 select FlowVersion .scalar_one_or_none() -> None (neu)
    #  3 update FlowVersion (deactivate others)
    #  4 select existing State .scalars().all() -> keine (frischer Flow)
    #  5 select Transition.id .scalars().all() -> keine
    #  6 update Application where current_state_id is None
    #  7,8 audit
    s, sess = svc(
        [res(), res(), res(), res(), res(), res(), *audit_results()]
    )
    out = await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    assert out.active is True
    assert out.version == 1
    assert sess.committed == 1
    # FlowVersion + 2 States hinzugefügt
    added_types = [type(o).__name__ for o in sess.added]
    assert "FlowVersion" in added_types
    assert added_types.count("State") == 2
    assert added_types.count("Transition") == 1


async def test_create_global_flow_version_new_version_remaps_apps() -> None:
    """Save legt eine NEUE, unveränderliche FlowVersion an (#config-versioning); ein
    laufender Antrag wird per State-KEY auf die jüngste Version gezogen (entfernter
    Key → Initial). Frische State-/Transition-Zeilen, **kein** Löschen alter Versionen.

    DB: ``app_keys`` (execute) liefert einen Antrag auf entferntem Key ``legacy``;
    ``max_version`` (scalar) = 3 ⇒ neue Version 4; alle übrigen execute-Aufrufe
    (deactivate, per-App-Update, None-Update, config_revision-Record) fallen auf das
    leere Default-Result zurück; ``head`` (scalar) = None.
    """
    graph = _two_state_graph()
    app_id = uuid.uuid4()
    s, sess = svc([res((app_id, "legacy"))], scalars=[3])
    out = await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    assert out.version == 4
    assert out.active is True
    added_types = [type(o).__name__ for o in sess.added]
    assert added_types.count("FlowVersion") == 1
    # Frische States (kein Reuse einer Altversion) + Transition.
    assert added_types.count("State") == 2
    assert added_types.count("Transition") == 1
    # Append-only: nichts wird gelöscht (frühere Version bleibt erhalten).
    assert sess.deleted == []
    assert sess.committed == 1


async def test_create_global_flow_version_no_apps_bumps_version() -> None:
    """Ohne laufende Anträge: neue Version = ``max+1``; der ``current_state_id IS NULL``-
    Sammel-Update läuft; nichts wird gelöscht."""
    graph = _two_state_graph()
    s, sess = svc([res()], scalars=[5])  # keine Anträge; max=5 → neue Version 6
    out = await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    assert out.version == 6
    assert out.active is True
    assert sess.deleted == []
    assert sess.committed == 1


async def test_create_global_flow_version_transition_explicit_order() -> None:
    """``trans.order`` gesetzt ⇒ wird übernommen (Branch order is not None)."""
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
    # Kein Initial-State → ValidationProblem vor jedem DB-Zugriff
    graph = FlowGraph.model_validate(
        {"states": [{"key": "a", "label": {"de": "A"}}], "transitions": []}
    )
    s, _ = svc()
    with pytest.raises(ValidationProblem) as ei:
        await s.create_global_flow_version(FlowVersionCreate(graph=graph), "admin")
    assert ei.value.status == 422


# --------------------------------------------------------------------------- #
# Rollen
# --------------------------------------------------------------------------- #
async def test_list_roles_groups_permissions() -> None:
    r1 = role_row(key="a")
    r2 = role_row(key="b")
    perm = Row(role_id=r1.id, permission="x.read")
    perm2 = Row(role_id=r1.id, permission="x.write")
    # scalars(roles) ; scalars(perms)
    s, _ = svc([res(r1, r2), res(perm, perm2)])
    out = await s.list_roles()
    by_key = {o.key: o for o in out}
    assert by_key["a"].permissions == ["x.read", "x.write"]
    assert by_key["b"].permissions == []


async def test_create_role_ok() -> None:
    # scalars(existing None) ; audit(2)
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
    # eine RolePermission-Zeile (dedupliziert)
    assert sum(type(o).__name__ == "RolePermission" for o in sess.added) == 1


async def test_create_role_conflict() -> None:
    s, _ = svc([res(role_row(key="dup"))])
    with pytest.raises(ConflictError):
        await s.create_role(RoleCreate(key="dup"), "admin")


async def test_update_role_label_and_permissions() -> None:
    role = role_row()
    # get(role) ; execute(delete perms) ; audit(2) ; scalars(perms after)
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
    # label None (Branch 572->574 übersprungen) ; permissions gesetzt
    role = role_row(name_i18n={"de": "Alt"})
    s, _ = svc(
        [res(), *audit_results(), res("application.create")],
        gets=[role],
    )
    out = await s.update_role(
        role.id, RoleUpdate(permissions=["application.create"]), "admin"
    )
    assert role.name_i18n == {"de": "Alt"}  # unverändert
    assert out.permissions == ["application.create"]


async def test_update_role_no_permissions_change() -> None:
    role = role_row()
    # permissions None → kein delete; audit(2) ; scalars(perms after = leer)
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


# --------------------------------------------------------------------------- #
# Role-Assignments
# --------------------------------------------------------------------------- #
async def test_list_role_assignments() -> None:
    s, _ = svc([res(assignment_row(), assignment_row())])
    out = await s.list_role_assignments()
    assert len(out) == 2


async def test_create_role_assignment_ok() -> None:
    principal = principal_row()
    role = role_row()
    # get(principal) ; get(role) ; audit(2)
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
    # get(RoleAssignmentRow row) ; get(Role new_role for existence) ;
    # _guard: get(Role old_role by row.role_id) ; audit(2)
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
    # AUD-031: _guard_self_admin_removal läuft jetzt IMMER zuerst. Bei einer
    # Nicht-Admin-Rolle (editor) kehrt der Guard ohne Konflikt zurück.
    # gets: get(row) ; guard: get(Role row.role_id=editor) ; existence: get(Role)
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
    # row hat admin-Rolle, principal.sub == actor → ConflictError beim Rollen-Wechsel
    principal = principal_row(sub="me")
    row = assignment_row(principal_id=principal.id)
    new_role = role_row(key="editor")
    admin_role = role_row(key="admin")
    # AUD-031: Guard läuft zuerst → get(row) ; guard: get(admin_role) ; get(principal)
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
    # AUD-031: Eine Nicht-role_id-Mutation (valid_until in der Vergangenheit) der
    # EIGENEN Admin-Zuweisung darf nicht durchgehen — sonst Selbst-Ablauf des Admins.
    principal = principal_row(sub="me")
    row = assignment_row(principal_id=principal.id)
    admin_role = role_row(key="admin")
    # get(row) ; guard: get(admin_role) ; get(principal)
    s, sess = svc(gets=[row, admin_role, principal])
    with pytest.raises(ConflictError):
        await s.update_role_assignment(
            row.id,
            RoleAssignmentUpdate(validUntil="2000-01-01T00:00:00Z"),
            "me",
        )
    assert sess.committed == 0
    assert row.valid_until is None  # unverändert


async def test_delete_role_assignment_ok() -> None:
    # get(assignment row) ; guard: get(editor → not admin) ;
    # member-check: get(editor → key != member) ; audit(2)
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
    # get(assignment) ; guard: not admin ; member-role + gremium_id None → Conflict
    row = assignment_row(gremium_id=None)
    guard_role = role_row(key="editor")
    member_role = role_row(key="member")
    s, _ = svc(gets=[row, guard_role, member_role])
    with pytest.raises(ConflictError):
        await s.delete_role_assignment(row.id, "admin")


async def test_delete_role_assignment_member_with_gremium_ok() -> None:
    # member-role aber gremium_id gesetzt → löschbar (Branch: gremium_id not None)
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
    # get(assignment) ; guard: get(admin_role) → admin ; get(principal) →
    # sub == actor → Conflict
    s, _ = svc(gets=[row, admin_role, principal])
    with pytest.raises(ConflictError):
        await s.delete_role_assignment(row.id, "me")


async def test_guard_self_admin_role_none_returns() -> None:
    # _guard_self_admin_removal: role None → früh return (kein Conflict)
    row = assignment_row()
    s, _ = svc(gets=[None])
    await s._guard_self_admin_removal(row, "anyone")  # darf NICHT werfen


async def test_guard_self_admin_other_principal_ok() -> None:
    # role admin, aber principal.sub != actor → kein Conflict
    row = assignment_row()
    admin_role = role_row(key="admin")
    other = principal_row(sub="someone-else")
    s, _ = svc(gets=[admin_role, other])
    await s._guard_self_admin_removal(row, "actor-sub")


async def test_guard_self_admin_principal_none_ok() -> None:
    # role admin, principal None → kein Conflict (Branch principal is None)
    row = assignment_row()
    admin_role = role_row(key="admin")
    s, _ = svc(gets=[admin_role, None])
    await s._guard_self_admin_removal(row, "actor")


# --------------------------------------------------------------------------- #
# Principals / Permissions
# --------------------------------------------------------------------------- #
async def test_search_principals_with_query_and_assignments() -> None:
    p1 = principal_row(sub="alice")
    p2 = principal_row(sub="bob")
    a1 = assignment_row(principal_id=p1.id)
    # scalars(principals) ; scalars(assignments)
    s, _ = svc([res(p1, p2), res(a1)])
    out = await s.search_principals("ali")
    by_sub = {o.sub: o for o in out}
    assert len(by_sub["alice"].assignments) == 1
    assert by_sub["bob"].assignments == []


async def test_search_principals_no_query_no_results() -> None:
    # query None → kein where; keine Principals → assignments-Query wird übersprungen
    s, _ = svc([res()])
    out = await s.search_principals(None)
    assert out == []


async def test_set_principal_active_activate() -> None:
    principal = principal_row(active=False, sub="x")
    # get(principal) ; audit(2) ; scalars(assignments)
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


# --------------------------------------------------------------------------- #
# Group-Mappings
# --------------------------------------------------------------------------- #
async def test_list_group_mappings() -> None:
    s, _ = svc([res(mapping_row(), mapping_row())])
    out = await s.list_group_mappings()
    assert len(out) == 2


async def test_create_group_mapping_ok() -> None:
    role = role_row()
    # get(role) ; audit(2)
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
    # get(mapping row) ; get(role existence) ; audit(2)
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


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #
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
    # secret wurde serverseitig erzeugt (32 Bytes)
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


# --------------------------------------------------------------------------- #
# AUD-062: CRUD-Zeit-Advisory SSRF-Prüfung der Webhook-URL
# --------------------------------------------------------------------------- #
def test_webhook_url_advisory_blocks_internal_ip_literal() -> None:
    # Metadaten-IP (link-local) ist nicht global → 400, kein stilles Dead-Letter.
    with pytest.raises(BadRequestError):
        ConfigService._assert_webhook_url_advisory("http://169.254.169.254/")


def test_webhook_url_advisory_blocks_private_ip_literal() -> None:
    with pytest.raises(BadRequestError):
        ConfigService._assert_webhook_url_advisory("http://10.0.0.1/hook")


def test_webhook_url_advisory_blocks_bad_scheme() -> None:
    with pytest.raises(BadRequestError):
        ConfigService._assert_webhook_url_advisory("ftp://example.com/")


def test_webhook_url_advisory_allows_global_ip_literal() -> None:
    # Globale IP-Literal löst keine Blockade aus (kein DNS).
    ConfigService._assert_webhook_url_advisory("https://1.1.1.1/hook")


def test_webhook_url_advisory_dns_failure_is_non_blocking() -> None:
    # Nicht auflösbarer Host (.example reserviert) → best-effort, nicht blockieren.
    ConfigService._assert_webhook_url_advisory("https://x.example/h")


# --------------------------------------------------------------------------- #
# AUD-062 (2. Hälfte): Delivery-Status-Diagnose-Read
# --------------------------------------------------------------------------- #
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
    # ok → delivered; pending → in_progress.
    assert _delivery_reason_class("ok", 200) == "delivered"
    assert _delivery_reason_class("pending", None) == "in_progress"
    # dead ohne HTTP-Code (SSRF-Block ODER Transport/DNS) → unreachable_or_blocked,
    # OHNE die geblockte IP zu nennen.
    assert _delivery_reason_class("dead", None) == "unreachable_or_blocked"
    # failed (Retry läuft) ohne Code → transienter Transportfehler.
    assert _delivery_reason_class("failed", None) == "transient_transport_error"
    # 4xx = Ziel lehnt ab; 5xx = Ziel-Serverfehler.
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
    # Vertippter/interner Webhook → dead ohne HTTP-Code; die Sicht nennt NUR die
    # grobe Klasse, keine aufgelöste IP / keinen Host.
    row = delivery_row(status="dead", response_code=None, attempts=5)
    out = _delivery_status_out(row.webhook_id, row)
    assert out.last_state == "dead"
    assert out.reason_class == "unreachable_or_blocked"
    assert out.attempts == 5
    # Kein IP-/Host-/Body-Feld im Diagnose-DTO.
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
    # Webhook-Liste über scalars-Queue (_results); je Hook eine latest-Delivery
    # über die scalar-Queue (_scalars), in derselben Reihenfolge.
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
    # Hook ohne Delivery → never.
    assert out[1].webhook_id == hook_b.id
    assert out[1].last_state == "never"


# --------------------------------------------------------------------------- #
# AUD-053: Role permission whitelist validation
# --------------------------------------------------------------------------- #
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
