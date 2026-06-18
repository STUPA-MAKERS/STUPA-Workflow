"""Unit-Coverage für das config_revision-Modul (DB-los, #config-versioning).

Treibt ``_flatten``/``_lock_key``, ``ConfigRevisionService`` (record/head/get/list_for/
diff), ``RevertService`` (alle Fehler-Branches) und ``reapply_snapshot`` (else-Branch)
über den Queue-Fake aus ``tests._support.auth_fakes``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.config_revision.models import ConfigRevision
from app.modules.config_revision.reapply import reapply_snapshot
from app.modules.config_revision.revert import RevertService
from app.modules.config_revision.schemas import ConfigRevisionOut
from app.modules.config_revision.service import (
    ENTITY_FLOW,
    GLOBAL_ID,
    ConfigRevisionService,
    _flatten,
    _lock_key,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests._support.auth_fakes import fake_session, result


def _rev(**kw: object) -> ConfigRevision:
    row = ConfigRevision(**kw)  # type: ignore[arg-type]
    if getattr(row, "id", None) is None:
        row.id = uuid.uuid4()
    return row


# --------------------------------------------------------------------------- #
# _flatten
# --------------------------------------------------------------------------- #
def test_flatten_form_keys_by_field() -> None:
    flat = _flatten(
        "form",
        {"fields": [{"key": "a", "type": "text"}, {"no_key": 1}], "description": {"de": "x"}},
    )
    assert flat == {"field:a": {"key": "a", "type": "text"}, "meta:description": {"de": "x"}}


def test_flatten_flow_keys_states_and_transitions() -> None:
    flat = _flatten(
        "flow",
        {
            "states": [{"key": "s1"}, {"nokey": 1}],
            "transitions": [
                {"from": "s1", "to": "s2"},
                {"from": "s2", "to": "s3", "branch": "pass"},
            ],
            "layout": {"x": 1},
        },
    )
    assert "state:s1" in flat
    assert "transition:s1->s2" in flat
    assert "transition:s2->s3:pass" in flat
    assert flat["meta:layout"] == {"x": 1}


def test_flatten_site_config_is_identity() -> None:
    assert _flatten("site_config", {"appName": "X"}) == {"appName": "X"}


def test_flatten_unknown_entity_is_identity() -> None:
    assert _flatten("other", {"k": 1}) == {"k": 1}


# --------------------------------------------------------------------------- #
# _lock_key
# --------------------------------------------------------------------------- #
def test_lock_key_stable_distinct_and_in_bigint_range() -> None:
    k = _lock_key("flow", "global")
    assert k == _lock_key("flow", "global")  # deterministisch
    assert _lock_key("form", "x") != _lock_key("form", "y")
    assert -(2**63) <= k < 2**63  # passt in Postgres bigint


# --------------------------------------------------------------------------- #
# ConfigRevisionService.record / head / get / list_for
# --------------------------------------------------------------------------- #
async def test_record_first_revision_no_prev() -> None:
    db = fake_session(result(), result(), result(), result())  # lock, head→None, audit×2
    rev = await ConfigRevisionService(db).record(
        entity_type=ENTITY_FLOW,
        entity_id=GLOBAL_ID,
        snapshot={"a": 1},
        actor="admin",
        action=AuditAction.CONFIG_ACTIVATION,
    )
    assert rev.version == 1
    assert rev.prev_revision_id is None
    assert rev.snapshot == {"a": 1}
    assert any(type(o).__name__ == "ConfigRevision" for o in db.added)
    assert any(type(o).__name__ == "AuditEntry" for o in db.added)


async def test_record_chains_from_head() -> None:
    prev = _rev(entity_type=ENTITY_FLOW, entity_id=GLOBAL_ID, version=2, snapshot={})
    db = fake_session(result(), result(prev), result(), result())  # lock, head→prev, audit×2
    rev = await ConfigRevisionService(db).record(
        entity_type=ENTITY_FLOW,
        entity_id=GLOBAL_ID,
        snapshot={"b": 2},
        actor="admin",
        extra_data={"global": True},
    )
    assert rev.version == 3
    assert rev.prev_revision_id == prev.id


async def test_head_get_list_for() -> None:
    rev = _rev(entity_type="form", entity_id="t1", version=1)
    assert await ConfigRevisionService(fake_session(result(rev))).head("form", "t1") is rev
    assert await ConfigRevisionService(fake_session(gets=[rev])).get(rev.id) is rev
    assert await ConfigRevisionService(fake_session()).get("not-a-uuid") is None
    assert await ConfigRevisionService(fake_session(result(rev))).list_for("form", "t1") == [rev]


async def test_resolve_versions_maps_id_to_version() -> None:
    a = _rev(entity_type="form", entity_id="t1", version=1)
    b = _rev(entity_type="form", entity_id="t1", version=2)
    assert await ConfigRevisionService(fake_session()).resolve_versions([a, b]) == {
        a.id: 1,
        b.id: 2,
    }


# --------------------------------------------------------------------------- #
# ConfigRevisionService.diff
# --------------------------------------------------------------------------- #
async def test_diff_against_previous_snapshot() -> None:
    prev = _rev(
        entity_type="form",
        entity_id="t1",
        version=1,
        snapshot={"fields": [{"key": "a", "type": "text"}]},
    )
    cur = _rev(
        entity_type="form",
        entity_id="t1",
        version=2,
        snapshot={"fields": [{"key": "a", "type": "number"}]},
    )
    cur.prev_revision_id = prev.id
    d = await ConfigRevisionService(fake_session(gets=[prev])).diff(cur)
    assert "field:a" in d["changed"]


async def test_diff_first_revision_is_all_added() -> None:
    cur = _rev(
        entity_type="site_config", entity_id=GLOBAL_ID, version=1, snapshot={"appName": "X"}
    )
    d = await ConfigRevisionService(fake_session()).diff(cur)
    assert d["added"] == {"appName": "X"}
    assert d["removed"] == {} and d["changed"] == {}


# --------------------------------------------------------------------------- #
# RevertService — Fehler-Branches (Erfolg = Integrationstest)
# --------------------------------------------------------------------------- #
async def test_revert_unknown_entry_404() -> None:
    with pytest.raises(NotFoundError):
        await RevertService(fake_session(result())).revert(1, "admin")


async def test_revert_without_revision_id_conflict() -> None:
    entry = AuditEntry(id=1, action="login", data={})
    with pytest.raises(ConflictError) as ei:
        await RevertService(fake_session(result(entry))).revert(1, "admin")
    assert ei.value.code == "not_revertable"


async def test_revert_missing_recorded_revision_404() -> None:
    rid = uuid.uuid4()
    entry = AuditEntry(id=1, action="config_change", data={"revisionId": str(rid)})
    # entry select → entry; get(recorded) → None
    with pytest.raises(NotFoundError):
        await RevertService(fake_session(result(entry), gets=[None])).revert(1, "admin")


async def test_revert_first_state_nothing_to_revert() -> None:
    rid = uuid.uuid4()
    entry = AuditEntry(id=1, action="config_change", data={"revisionId": str(rid)})
    recorded = _rev(entity_type=ENTITY_FLOW, entity_id=GLOBAL_ID, version=1)
    recorded.id = rid
    recorded.prev_revision_id = None
    with pytest.raises(ConflictError) as ei:
        await RevertService(fake_session(result(entry), gets=[recorded])).revert(1, "admin")
    assert ei.value.code == "nothing_to_revert"


async def test_revert_status_missing_state_ids_not_revertable() -> None:
    # status_change ohne from/to im data → Dispatcher liefert not_revertable (DB-los).
    entry = AuditEntry(
        id=1, action="status_change", target_id="app-1", data={"toStateId": "b"}
    )
    with pytest.raises(ConflictError) as ei:
        await RevertService(fake_session(result(entry))).revert(1, "admin")
    assert ei.value.code == "not_revertable"


async def test_revert_non_revertable_budget_action() -> None:
    # Löschungen (budget_expense_delete) sind bewusst nicht revertierbar.
    entry = AuditEntry(
        id=1, action="budget_expense_delete", target_id="x", data={}
    )
    with pytest.raises(ConflictError) as ei:
        await RevertService(fake_session(result(entry))).revert(1, "admin")
    assert ei.value.code == "not_revertable"


async def test_revert_stale_when_newer_head_exists() -> None:
    rid, pid = uuid.uuid4(), uuid.uuid4()
    entry = AuditEntry(id=1, action="config_change", data={"revisionId": str(rid)})
    recorded = _rev(entity_type=ENTITY_FLOW, entity_id=GLOBAL_ID, version=2)
    recorded.id = rid
    recorded.prev_revision_id = pid
    prev = _rev(entity_type=ENTITY_FLOW, entity_id=GLOBAL_ID, version=1)
    prev.id = pid
    head = _rev(entity_type=ENTITY_FLOW, entity_id=GLOBAL_ID, version=3)
    # entry select; head scalar (≠ recorded); gets: recorded, prev
    db = fake_session(result(entry), result(head), gets=[recorded, prev])
    with pytest.raises(ConflictError) as ei:
        await RevertService(db).revert(1, "admin")
    assert ei.value.code == "stale_revert"


# --------------------------------------------------------------------------- #
# reapply_snapshot — unbekannte Entität
# --------------------------------------------------------------------------- #
async def test_reapply_unsupported_entity_type() -> None:
    with pytest.raises(ValidationProblem):
        await reapply_snapshot(
            fake_session(),
            entity_type="bogus",
            entity_id="x",
            snapshot={},
            actor="admin",
            action=AuditAction.CONFIG_CHANGE,
        )


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
def test_config_revision_out_from_row() -> None:
    row = _rev(entity_type="form", entity_id="t1", version=2, created_by="sub")
    row.at = datetime(2026, 6, 10, tzinfo=UTC)
    out = ConfigRevisionOut.from_row(row, created_by_name="Alice", is_current=True)
    assert out.version == 2
    assert out.created_by_name == "Alice"
    assert out.is_current is True
    assert out.entity_type == "form"
