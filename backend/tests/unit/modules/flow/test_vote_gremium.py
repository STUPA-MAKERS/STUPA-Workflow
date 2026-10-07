"""Flow variant B: the snapshot of the vote Gremium and the fail-closed rule.

`app.modules.flow.vote_gremium` resolves the Gremium of a vote state (fixed or from the
cost center). `FlowService` stores it with every state change, hides and refuses a
transition into a vote state without a Gremium, and fills the agenda Gremium of an
`addToNextSession` without `gremiumId`. The suite runs without a DB.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.flow import context as flow_context
from app.modules.flow import service as flow_service
from app.modules.flow import vote_gremium as vg
from app.modules.flow.service import FlowService
from app.shared.errors import ConflictError
from app.shared.guards import GuardContext
from tests._support.flow_fakes import fake_session, result

BUDGET = {"gremiumSource": "budget"}


def _state(kind: str = "vote", config: Any = None, state_id: UUID | None = None) -> Any:
    return SimpleNamespace(
        id=state_id or uuid4(), kind=kind, config=config if config is not None else {},
        flow_version_id=None,
    )


@pytest.fixture
def effective(monkeypatch: pytest.MonkeyPatch) -> dict[str, UUID | None]:
    """Patch the cost-center lookup: `value` is the effective deciding Gremium."""
    box: dict[str, UUID | None] = {"value": None}

    async def _eff(_session: object, budget_id: UUID | None) -> UUID | None:
        return box["value"] if budget_id is not None else None

    monkeypatch.setattr(vg, "effective_decision_gremium", _eff)
    return box


@pytest.fixture(autouse=True)
def _ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _bc(*_a: object, manual: bool, **_k: object) -> GuardContext:
        return GuardContext(manual=manual)

    monkeypatch.setattr(flow_context, "build_context", _bc)


# --- vote_gremium module -----------------------------------------------------------


def test_gremium_from_budget() -> None:
    assert vg.gremium_from_budget(_state(config=BUDGET)) is True
    assert vg.gremium_from_budget(_state(config={"gremiumId": "x"})) is False
    assert vg.gremium_from_budget(_state(kind="normal", config=BUDGET)) is False
    assert vg.gremium_from_budget(_state(config=None)) is False
    junk = cast(Any, SimpleNamespace(kind="vote", config="junk"))
    assert vg.gremium_from_budget(junk) is False
    assert vg.gremium_from_budget(None) is False


def test_fixed_gremium_ref() -> None:
    gid = uuid4()
    assert vg.fixed_gremium_ref(_state(config={"gremiumId": str(gid)})) == gid
    assert vg.fixed_gremium_ref(_state(config={"gremiumId": "nope"})) is None
    assert vg.fixed_gremium_ref(_state(config={"gremiumId": ""})) is None
    assert vg.fixed_gremium_ref(_state(config={})) is None


async def test_resolve_vote_gremium(effective: dict[str, UUID | None]) -> None:
    gid, budget = uuid4(), uuid4()
    db = fake_session()
    assert await vg.resolve_vote_gremium(db, None, budget) is None
    assert await vg.resolve_vote_gremium(db, _state(kind="normal"), budget) is None
    effective["value"] = gid
    assert await vg.resolve_vote_gremium(db, _state(config=BUDGET), budget) == gid
    assert await vg.resolve_vote_gremium(db, _state(config=BUDGET), None) is None
    # A fixed Gremium counts only when it exists.
    assert await vg.resolve_vote_gremium(db, _state(config={"gremiumId": "x"}), None) is None
    db.scalar_results = [gid]
    assert (
        await vg.resolve_vote_gremium(db, _state(config={"gremiumId": str(gid)}), None) == gid
    )
    assert (
        await vg.resolve_vote_gremium(db, _state(config={"gremiumId": str(gid)}), None)
        is None
    )


async def test_snapshot_for_entry(effective: dict[str, UUID | None]) -> None:
    db = fake_session()
    with pytest.raises(ConflictError) as err:
        await vg.snapshot_for_entry(db, _state(config=BUDGET), uuid4())
    assert err.value.code == vg.NO_VOTE_GREMIUM
    # A fixed vote state without an existing Gremium keeps today's behaviour.
    assert await vg.snapshot_for_entry(db, _state(config={"gremiumId": "x"}), None) is None
    assert await vg.snapshot_for_entry(db, _state(kind="normal"), None) is None
    effective["value"] = gid = uuid4()
    assert await vg.snapshot_for_entry(db, _state(config=BUDGET), uuid4()) == gid


async def test_in_budget_vote_state() -> None:
    db = fake_session()

    def _a(state: object, snap: object) -> Any:
        return cast(Any, SimpleNamespace(current_state_id=state, vote_gremium_id=snap))

    assert await vg.in_budget_vote_state(db, _a(None, uuid4())) is False
    # Without a snapshot the cost center stays open for a repair.
    assert await vg.in_budget_vote_state(db, _a(uuid4(), None)) is False
    db.get_results = [_state(config=BUDGET)]
    assert await vg.in_budget_vote_state(db, _a(uuid4(), uuid4())) is True
    db.get_results = [_state(config={"gremiumId": "x"})]
    assert await vg.in_budget_vote_state(db, _a(uuid4(), uuid4())) is False


async def test_fill_snapshot(effective: dict[str, UUID | None]) -> None:
    effective["value"] = gid = uuid4()
    db = fake_session()
    app = cast(Any, SimpleNamespace(current_state_id=None, vote_gremium_id=None, budget_id=uuid4()))
    await vg.fill_snapshot(db, app)
    assert app.vote_gremium_id is None
    app.current_state_id = uuid4()
    db.get_results = [_state(kind="normal")]
    await vg.fill_snapshot(db, app)
    assert app.vote_gremium_id is None
    db.get_results = [_state(config=BUDGET)]
    await vg.fill_snapshot(db, app)
    assert app.vote_gremium_id == gid
    # An existing snapshot stays.
    await vg.fill_snapshot(db, app)
    assert app.vote_gremium_id == gid


# --- FlowService -------------------------------------------------------------------


def _principal() -> Principal:
    return Principal(sub="mgr", roles=["chair"], permissions={"application.transition"})


def _app(state_id: object, *, budget_id: UUID | None = None) -> Any:
    return SimpleNamespace(
        id=uuid4(), current_state_id=state_id, flow_version_id=uuid4(),
        type_id=uuid4(), form_version_id=uuid4(), data={}, budget_id=budget_id,
        vote_gremium_id=None,
    )


def _t(app: Any, to_id: UUID, *, actions: list | None = None, automatic: bool = False) -> Any:
    return SimpleNamespace(
        id=uuid4(), flow_version_id=app.flow_version_id, from_state_id=app.current_state_id,
        to_state_id=to_id, label_i18n={}, color=None, guard=None,
        actions=actions or [], automatic=automatic, branch=None, requires_action=True,
    )


def test_agenda_action_helpers() -> None:
    assert flow_service._agenda_action(None) is None  # noqa: SLF001
    assert flow_service._agenda_action([{"type": "notify"}]) is None  # noqa: SLF001
    assert flow_service.agenda_gremium_id([{"type": "addToNextSession"}]) is None


async def test_available_hides_a_budget_vote_without_gremium(
    effective: dict[str, UUID | None],
) -> None:
    app = _app(uuid4(), budget_id=uuid4())
    gvote = _state(config=BUDGET)
    normal = _state(kind="normal")
    to_vote = _t(app, gvote.id, actions=[{"type": "addToNextSession"}])
    to_normal = _t(app, normal.id)
    db = fake_session(result(app), result(to_vote, to_normal))
    db.get_results = [gvote, normal]
    out = await FlowService(db).available_transitions(app.id, _principal(), deadline_passed=False)
    assert [t.id for t in out] == [to_normal.id]

    # With a deciding Gremium the transition shows, with that Gremium as agenda Gremium.
    effective["value"] = gid = uuid4()
    db = fake_session(result(app), result(to_vote, to_normal))
    db.get_results = [gvote, normal]
    out = await FlowService(db).available_transitions(app.id, _principal(), deadline_passed=False)
    by_id = {t.id: t for t in out}
    assert (by_id[to_vote.id].adds_to_agenda, by_id[to_vote.id].agenda_gremium_id) == (True, gid)
    assert by_id[to_normal.id].adds_to_agenda is False


async def test_agenda_gremium_explicit_and_fixed() -> None:
    app = _app(uuid4())
    explicit, fixed_id = uuid4(), uuid4()
    fixed = _state(config={"gremiumId": str(fixed_id)})
    t_explicit = _t(
        app, fixed.id, actions=[{"type": "addToNextSession", "gremiumId": str(explicit)}]
    )
    t_fallback = _t(app, fixed.id, actions=[{"type": "addToNextSession"}])
    db = fake_session()
    svc = FlowService(db)
    assert await svc._agenda_gremium(t_explicit, fixed, None) == explicit  # noqa: SLF001
    db.scalar_results = [fixed_id]
    assert await svc._agenda_gremium(t_fallback, fixed, None) == fixed_id  # noqa: SLF001
    assert await svc._agenda_gremium(t_fallback, None, None) is None  # noqa: SLF001


async def test_fire_into_a_budget_vote_without_gremium_409(
    effective: dict[str, UUID | None],
) -> None:
    app = _app(uuid4())
    gvote = _state(config=BUDGET)
    t = _t(app, gvote.id)
    db = fake_session(result(app), result(t))
    db.get_results = [gvote]
    with pytest.raises(ConflictError) as err:
        await FlowService(db).fire(app.id, t.id, _principal(), deadline_passed=False)
    assert err.value.code == "no_vote_gremium"
    assert db.committed == 0


async def test_fire_stores_the_snapshot(effective: dict[str, UUID | None]) -> None:
    effective["value"] = gid = uuid4()
    app = _app(uuid4(), budget_id=uuid4())
    gvote = _state(config=BUDGET)
    t = _t(app, gvote.id)
    db = fake_session(result(app), result(t), result(rowcount=1))
    db.get_results = [gvote]
    await FlowService(db).fire(app.id, t.id, _principal(), deadline_passed=False)
    update = db.statements[2]
    assert update.compile().params["vote_gremium_id"] == gid


async def test_auto_advance_skips_a_budget_vote_without_gremium(
    effective: dict[str, UUID | None],
) -> None:
    app = _app(uuid4())
    current = _state(kind="normal")
    gvote, normal = _state(config=BUDGET), _state(kind="normal")
    skipped = _t(app, gvote.id, automatic=True)
    manual = _t(app, normal.id)
    db = fake_session(result(app), result(current), result(manual, skipped))
    db.get_results = [gvote]
    assert await FlowService(db).auto_advance(app.id, _principal(), deadline_passed=False) is None


async def test_force_status_into_a_budget_vote_without_gremium_409(
    effective: dict[str, UUID | None],
) -> None:
    app = _app(uuid4())
    target = _state(config=BUDGET)
    target.flow_version_id = app.flow_version_id
    db = fake_session(result(app), result(target))
    with pytest.raises(ConflictError) as err:
        await FlowService(db).force_status(app.id, target.id, _principal(), note="x")
    assert err.value.code == "no_vote_gremium"


async def test_revert_into_a_budget_vote_without_gremium_409(
    effective: dict[str, UUID | None],
) -> None:
    to_id = uuid4()
    app = _app(to_id)
    restored = _state(config=BUDGET)
    db = fake_session(result(app))
    db.get_results = [restored]
    with pytest.raises(ConflictError) as err:
        await FlowService(db).revert_status(
            app.id, from_state_id=restored.id, to_state_id=to_id, actor="a",
            reverted_audit_id=1,
        )
    assert err.value.code == "no_vote_gremium"


async def test_check_agenda_meeting_uses_the_vote_gremium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.livevote.service as livevote_service
    from app.shared.errors import ValidationProblem

    class _Meetings:
        def __init__(self, _s: object) -> None: ...

        async def assert_can_read(self, *_a: object) -> None: ...

    monkeypatch.setattr(livevote_service, "MeetingService", _Meetings)
    gid = uuid4()
    app = _app(uuid4())
    gvote = _state(config=BUDGET)
    t = _t(app, gvote.id, actions=[{"type": "addToNextSession"}])
    meeting = SimpleNamespace(status="planned", gremium_id=gid)
    db = fake_session(result(gvote))
    db.get_results = [meeting]
    await FlowService(db)._check_agenda_meeting(  # noqa: SLF001
        t, uuid4(), _principal(), vote_gremium=gid
    )
    # Without a vote Gremium the transition does not add to an agenda.
    with pytest.raises(ValidationProblem):
        await FlowService(fake_session())._check_agenda_meeting(  # noqa: SLF001
            t, uuid4(), _principal()
        )


async def test_entry_snapshot_keeps_it_on_a_move_inside_the_vote_state(
    effective: dict[str, UUID | None],
) -> None:
    effective["value"] = uuid4()
    app = _app(uuid4(), budget_id=uuid4())
    app.vote_gremium_id = kept = uuid4()
    gvote = _state(config=BUDGET, state_id=app.current_state_id)
    svc = FlowService(fake_session())
    assert await svc._entry_snapshot(app, gvote.id, gvote) == kept  # noqa: SLF001
    # A move from another state resolves again.
    assert await svc._entry_snapshot(app, uuid4(), gvote) == effective["value"]  # noqa: SLF001


def test_budget_unchanged_pins_the_cost_center() -> None:
    app = _app(uuid4())
    assert FlowService._budget_unchanged(app, _state(kind="normal")) == []  # noqa: SLF001
    (clause,) = FlowService._budget_unchanged(app, _state(config=BUDGET))  # noqa: SLF001
    assert "IS NULL" in str(clause)
    app.budget_id = uuid4()
    (clause,) = FlowService._budget_unchanged(app, _state(config=BUDGET))  # noqa: SLF001
    assert "budget_id =" in str(clause)
