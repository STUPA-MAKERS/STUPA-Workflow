"""Unit (ohne DB): Vollabdeckung Gremium-Rollen + Site-Config-Service.

Ergänzt die bestehenden Suites um die noch nicht abgedeckten Service-Branches:
* Gremium-Rollen-CRUD (Konflikt/Not-Found/Pflichtrollen-Schutz, In-Use-Block),
* Pflichtrollen-Backfill (idempotent), Membership-Validierung,
* reine Helfer (``_parse_dt``/``_iso``/``_sanitize_perms``/``_role_out``),
* Site-Config Draft/Activate/Public/Manifest inkl. Fallback-Namen.

DB-frei: ``tests._support.auth_fakes.FakeSession`` liefert vorab gefüllte
Ergebnis-/``get``-Queues. Audit-``record`` setzt zwei ``execute``-Calls ab
(Advisory-Lock + prev-Hash) → je Audit zwei ``result()`` in der Queue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from app.modules.admin import gremium_roles as gr
from app.modules.admin.branding import Branding
from app.modules.admin.gremium_roles import (
    FORCED_ROLE_KEYS,
    GREMIUM_PERMISSIONS,
    GremiumRoleService,
    _iso,
    _parse_dt,
    _role_out,
    _sanitize_perms,
    active_gremium_roles,
    gremium_ids_with_permission,
    gremium_member_ids,
    intervals_overlap,
)
from app.modules.admin.models import GremiumMembership, GremiumRole, SiteConfigVersion
from app.modules.admin.schemas import (
    GremiumMembershipCreate,
    GremiumRoleCreate,
    GremiumRoleUpdate,
)
from app.modules.admin.site_config_service import (
    DEFAULT_APP_NAME,
    DEFAULT_APP_SHORT_NAME,
    SiteConfigService,
    _branding,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests._support.auth_fakes import fake_session, result


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def _role(gremium_id=None, key: str = "vorsitz", perms=None) -> GremiumRole:
    r = GremiumRole(
        gremium_id=gremium_id or uuid4(),
        key=key,
        name_i18n={"de": "Vorsitz"},
        permissions=perms or [],
    )
    r.id = uuid4()
    return r


def _membership(pid, gid, frm, until) -> GremiumMembership:
    m = GremiumMembership(
        principal_id=pid,
        gremium_id=gid,
        gremium_role_id=uuid4(),
        valid_from=frm,
        valid_until=until,
    )
    m.id = uuid4()
    return m


def _id_on_flush(db) -> None:
    """``flush`` der Auth-Fakes vergibt keine PK → wie in der Bestands-Suite nachrüsten."""
    orig_flush = db.flush

    async def _flush() -> None:
        for o in db.added:
            if getattr(o, "id", None) is None:
                o.id = uuid4()
        await orig_flush()

    db.flush = _flush


# =========================================================== reine Helfer/Queries


def test_intervals_overlap_all_branches() -> None:
    # a_from None -> left_ok kurzschluss True, dann right_ok prüfen
    assert intervals_overlap(None, _dt("2026-06-01"), _dt("2026-01-01"), _dt("2026-03-01"))
    # b_until None -> left_ok True
    assert intervals_overlap(_dt("2026-01-01"), _dt("2026-02-01"), _dt("2026-01-15"), None)
    # disjunkt: left_ok False (a_from >= b_until)
    assert not intervals_overlap(
        _dt("2026-06-01"), _dt("2026-09-01"), _dt("2026-01-01"), _dt("2026-03-01")
    )
    # right_ok False (b_from >= a_until), left_ok True
    assert not intervals_overlap(
        _dt("2026-01-01"), _dt("2026-03-01"), _dt("2026-06-01"), _dt("2026-09-01")
    )


def test_parse_dt_variants() -> None:
    assert _parse_dt(None) is None
    assert _parse_dt("") is None
    # naive -> UTC ergänzt
    naive = _parse_dt("2026-01-01T10:00:00")
    assert naive is not None and naive.tzinfo is UTC
    # mit Offset bleibt erhalten
    aware = _parse_dt("2026-01-01T10:00:00+02:00")
    assert aware is not None and aware.utcoffset() is not None


def test_iso() -> None:
    assert _iso(None) is None
    iso = _iso(_dt("2026-01-01"))
    assert iso is not None and iso.startswith("2026-01-01")


def test_sanitize_perms() -> None:
    assert _sanitize_perms(None) == []
    # dedupliziert + Katalog-Reihenfolge, Unbekanntes raus
    out = _sanitize_perms(["vote.cast", "bogus", "session.manage", "vote.cast"])
    assert out == [p for p in GREMIUM_PERMISSIONS if p in {"vote.cast", "session.manage"}]
    assert "bogus" not in out


def test_role_out_forced_flag_and_empty_name() -> None:
    forced = _role(key=next(iter(FORCED_ROLE_KEYS)))
    out = _role_out(forced)
    assert out.forced is True
    # name_i18n None -> {}
    r = GremiumRole(gremium_id=uuid4(), key="custom", name_i18n=None, permissions=None)
    r.id = uuid4()
    out2 = _role_out(r)
    assert out2.forced is False
    assert out2.name == {}
    assert out2.permissions == []


async def test_active_gremium_roles_and_permission_helpers() -> None:
    gid = uuid4()
    role = _role(gid, key="vorstand", perms=["session.manage", "vote.cast"])
    # active_gremium_roles: execute -> rows of (gremium_id, role)
    db = fake_session(result((gid, role)))
    pairs = await active_gremium_roles(db, "sub-1", now=_dt("2026-06-01"))
    assert pairs == [(gid, role)]

    # gremium_ids_with_permission: perm vorhanden
    db2 = fake_session(result((gid, role)))
    assert await gremium_ids_with_permission(db2, "sub-1", "session.manage") == {gid}
    # perm fehlt -> leeres set
    db3 = fake_session(result((gid, role)))
    assert await gremium_ids_with_permission(db3, "sub-1", "protocol.write") == set()
    # Rolle ohne permissions (None) -> kein Treffer
    role_none = _role(gid, key="x", perms=None)
    role_none.permissions = cast("list[str]", None)
    db4 = fake_session(result((gid, role_none)))
    assert await gremium_ids_with_permission(db4, "sub-1", "vote.cast") == set()

    # gremium_member_ids
    db5 = fake_session(result((gid, role)))
    assert await gremium_member_ids(db5, "sub-1") == {gid}


async def test_active_gremium_roles_default_now() -> None:
    # now=None -> datetime.now(UTC)-Zweig
    db = fake_session(result())
    assert await active_gremium_roles(db, "nobody") == []


# ==================================================== ensure_forced_roles / list


async def test_ensure_forced_roles_adds_when_missing() -> None:
    gid = uuid4()
    # present keys: keine vorhanden -> alle drei werden angelegt
    db = fake_session(result())  # scalars(present keys) -> leer
    svc = GremiumRoleService(db)
    added = await svc.ensure_forced_roles(gid)
    assert added is True
    assert len(db.added) == 3
    assert db.flushed == 1
    assert {o.key for o in db.added} == set(FORCED_ROLE_KEYS)


async def test_ensure_forced_roles_idempotent_when_all_present() -> None:
    gid = uuid4()
    db = fake_session(result(*FORCED_ROLE_KEYS))  # alle keys schon da
    svc = GremiumRoleService(db)
    added = await svc.ensure_forced_roles(gid)
    assert added is False
    assert db.added == []
    assert db.flushed == 0


async def test_list_roles_backfills_then_commits() -> None:
    gid = uuid4()
    # 1) ensure_forced_roles scalars(present) -> leer (=> added True, commit)
    # 2) scalars(rows) -> die nun vorhandenen Rollen
    r1 = _role(gid, key="vorstand")
    db = fake_session(result(), result(r1))
    svc = GremiumRoleService(db)
    out = await svc.list_roles(gid)
    assert db.committed == 1  # weil backfill etwas angelegt hat
    assert [o.key for o in out] == ["vorstand"]


async def test_list_roles_no_backfill_no_commit() -> None:
    gid = uuid4()
    r1 = _role(gid, key="manager")
    # present keys = alle Pflichtrollen -> kein add, kein commit
    db = fake_session(result(*FORCED_ROLE_KEYS), result(r1))
    svc = GremiumRoleService(db)
    out = await svc.list_roles(gid)
    assert db.committed == 0
    assert len(out) == 1


# ============================================================== create/update role


async def test_create_role_conflict_on_duplicate_key() -> None:
    gid = uuid4()
    existing = _role(gid, key="reviewer")
    db = fake_session(result(existing))  # scalars(existing) -> first() != None
    svc = GremiumRoleService(db)
    with pytest.raises(ConflictError):
        await svc.create_role(gid, GremiumRoleCreate(key="reviewer"), "admin")


async def test_create_role_success_sanitizes_perms() -> None:
    gid = uuid4()
    db = fake_session(
        result(),  # scalars(existing) -> keiner
        result(),  # audit advisory lock
        result(),  # audit prev-hash
    )
    _id_on_flush(db)
    svc = GremiumRoleService(db)
    payload = GremiumRoleCreate(
        key="reviewer",
        name={"de": "Prüfer"},
        permissions=["vote.cast", "bogus", "session.manage"],
    )
    out = await svc.create_role(gid, payload, "admin")
    assert out.key == "reviewer"
    assert "bogus" not in out.permissions
    assert set(out.permissions) == {"vote.cast", "session.manage"}
    assert db.committed == 1
    # genau eine GremiumRole angelegt (zusätzlich hängt der Audit-Eintrag dran)
    assert sum(isinstance(o, GremiumRole) for o in db.added) == 1


async def test_update_role_not_found() -> None:
    db = fake_session(gets=[None])  # get -> None
    svc = GremiumRoleService(db)
    with pytest.raises(NotFoundError):
        await svc.update_role(uuid4(), GremiumRoleUpdate(name={"de": "X"}), "admin")


async def test_update_role_updates_name_and_perms() -> None:
    role = _role(key="custom", perms=["vote.cast"])
    db = fake_session(result(), result(), gets=[role])  # audit 2x execute
    svc = GremiumRoleService(db)
    out = await svc.update_role(
        role.id,
        GremiumRoleUpdate(name={"de": "Neu"}, permissions=["session.manage"]),
        "admin",
    )
    assert out.name == {"de": "Neu"}
    assert out.permissions == ["session.manage"]
    assert db.committed == 1


async def test_update_role_keeps_fields_when_none() -> None:
    role = _role(key="custom", perms=["vote.cast"])
    role.name_i18n = {"de": "Alt"}
    db = fake_session(result(), result(), gets=[role])
    svc = GremiumRoleService(db)
    # name=None und permissions=None -> beide Zweige übersprungen
    out = await svc.update_role(role.id, GremiumRoleUpdate(), "admin")
    assert out.name == {"de": "Alt"}
    assert out.permissions == ["vote.cast"]


# ===================================================================== delete role


async def test_delete_role_not_found() -> None:
    db = fake_session(gets=[None])
    svc = GremiumRoleService(db)
    with pytest.raises(NotFoundError):
        await svc.delete_role(uuid4(), "admin")


async def test_delete_role_forced_blocked() -> None:
    forced = _role(key=next(iter(FORCED_ROLE_KEYS)))
    db = fake_session(gets=[forced])
    svc = GremiumRoleService(db)
    with pytest.raises(ConflictError, match="forced"):
        await svc.delete_role(forced.id, "admin")


async def test_delete_role_in_use_blocked() -> None:
    role = _role(key="custom")
    db = fake_session(result(uuid4()), gets=[role])  # scalars(in_use) -> first() != None
    svc = GremiumRoleService(db)
    with pytest.raises(ConflictError, match="in use"):
        await svc.delete_role(role.id, "admin")


async def test_delete_role_success() -> None:
    role = _role(key="custom")
    db = fake_session(
        result(),  # scalars(in_use) -> leer
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        gets=[role],
    )
    svc = GremiumRoleService(db)
    await svc.delete_role(role.id, "admin")
    assert role in db.deleted
    assert db.committed == 1


# ===================================================================== memberships


async def test_list_memberships() -> None:
    gid, pid = uuid4(), uuid4()
    m = _membership(pid, gid, _dt("2026-01-01"), _dt("2026-12-31"))
    db = fake_session(result(m))
    svc = GremiumRoleService(db)
    out = await svc.list_memberships(gid)
    assert len(out) == 1
    assert out[0].valid_from is not None and out[0].valid_until is not None


async def test_create_membership_role_not_found() -> None:
    db = fake_session(gets=[None])  # get(role) -> None
    svc = GremiumRoleService(db)
    payload = GremiumMembershipCreate(principalId=uuid4(), gremiumRoleId=uuid4())
    with pytest.raises(NotFoundError, match="gremium role"):
        await svc.create_membership(uuid4(), payload, "admin")


async def test_create_membership_role_wrong_gremium() -> None:
    role = _role(gremium_id=uuid4())  # andere gremium_id
    db = fake_session(gets=[role])
    svc = GremiumRoleService(db)
    payload = GremiumMembershipCreate(principalId=uuid4(), gremiumRoleId=role.id)
    with pytest.raises(ConflictError, match="does not belong"):
        await svc.create_membership(uuid4(), payload, "admin")


async def test_create_membership_unknown_principal_404() -> None:
    gid = uuid4()
    role = _role(gid)
    db = fake_session(gets=[role])  # zweiter get (Principal) -> None
    svc = GremiumRoleService(db)
    payload = GremiumMembershipCreate(principalId=uuid4(), gremiumRoleId=role.id)
    with pytest.raises(NotFoundError, match="principal"):
        await svc.create_membership(gid, payload, "admin")


async def test_create_membership_rejects_overlap() -> None:
    gid, pid = uuid4(), uuid4()
    role = _role(gid)
    existing = _membership(pid, gid, _dt("2026-01-01"), _dt("2026-12-31"))
    db = fake_session(result(existing), gets=[role, object()])
    svc = GremiumRoleService(db)
    payload = GremiumMembershipCreate(
        principalId=pid,
        gremiumRoleId=role.id,
        validFrom="2026-06-01",
        validUntil="2026-09-01",
    )
    with pytest.raises(ConflictError, match="overlapping"):
        await svc.create_membership(gid, payload, "admin")


async def test_create_membership_from_after_until_rejected() -> None:
    gid = uuid4()
    role = _role(gid)
    db = fake_session(gets=[role, object()])  # Rolle + Principal-Existenz
    svc = GremiumRoleService(db)
    payload = GremiumMembershipCreate(
        principalId=uuid4(),
        gremiumRoleId=role.id,
        validFrom="2026-12-01",
        validUntil="2026-01-01",
    )
    with pytest.raises(ValidationProblem):
        await svc.create_membership(gid, payload, "admin")


async def test_create_membership_equal_from_until_rejected() -> None:
    gid = uuid4()
    role = _role(gid)
    db = fake_session(gets=[role, object()])
    svc = GremiumRoleService(db)
    payload = GremiumMembershipCreate(
        principalId=uuid4(),
        gremiumRoleId=role.id,
        validFrom="2026-01-01T00:00:00",
        validUntil="2026-01-01T00:00:00",
    )
    with pytest.raises(ValidationProblem):
        await svc.create_membership(gid, payload, "admin")


async def test_create_membership_success_no_overlap() -> None:
    gid, pid = uuid4(), uuid4()
    role = _role(gid)
    existing = _membership(pid, gid, _dt("2025-01-01"), _dt("2026-01-01"))
    db = fake_session(
        result(existing),  # scalars(existing memberships)
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        gets=[role, object()],
    )
    _id_on_flush(db)
    svc = GremiumRoleService(db)
    payload = GremiumMembershipCreate(
        principalId=pid,
        gremiumRoleId=role.id,
        validFrom="2026-01-01",
        validUntil="2027-01-01",
    )
    out = await svc.create_membership(gid, payload, "admin")
    assert out.valid_from is not None
    assert db.committed == 1


async def test_create_membership_open_ended_no_existing() -> None:
    # valid_from/until None (offene Amtszeit), keine bestehenden Mitgliedschaften
    gid, pid = uuid4(), uuid4()
    role = _role(gid)
    db = fake_session(
        result(),  # scalars(existing) -> leer
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        gets=[role, object()],
    )
    _id_on_flush(db)
    svc = GremiumRoleService(db)
    payload = GremiumMembershipCreate(principalId=pid, gremiumRoleId=role.id)
    out = await svc.create_membership(gid, payload, "admin")
    assert out.valid_from is None
    assert out.valid_until is None
    assert db.committed == 1


async def test_delete_membership_not_found() -> None:
    db = fake_session(gets=[None])
    svc = GremiumRoleService(db)
    with pytest.raises(NotFoundError):
        await svc.delete_membership(uuid4(), "admin")


async def test_delete_membership_success() -> None:
    m = _membership(uuid4(), uuid4(), None, None)
    db = fake_session(result(), result(), gets=[m])  # audit 2x execute
    svc = GremiumRoleService(db)
    await svc.delete_membership(m.id, "admin")
    assert m in db.deleted
    assert db.committed == 1


# ============================================================== Site-Config-Service


def _scv(version: int, *, active: bool, branding=None) -> SiteConfigVersion:
    row = SiteConfigVersion(
        version=version,
        active=active,
        branding=branding if branding is not None else Branding().model_dump(by_alias=True),
        created_by="admin",
    )
    row.id = uuid4()
    return row


def test_branding_helper_none_and_row() -> None:
    assert isinstance(_branding(None), Branding)
    row = _scv(1, active=True, branding=Branding(appName="X").model_dump(by_alias=True))
    assert _branding(row).app_name == "X"


async def test_get_no_versions() -> None:
    # _active -> None, _latest -> None => latest is None Zweig
    db = fake_session(result(), result())
    out = await SiteConfigService(db).get()
    assert out.version == 0
    assert out.has_draft_changes is False


async def test_get_latest_is_active_no_draft() -> None:
    active = _scv(3, active=True)
    # _active -> active, _latest -> active (latest.active True)
    db = fake_session(result(active), result(active))
    out = await SiteConfigService(db).get()
    assert out.version == 3
    assert out.has_draft_changes is False


async def test_get_with_pending_draft() -> None:
    active = _scv(3, active=True)
    draft = _scv(4, active=False, branding=Branding(appName="Draft").model_dump(by_alias=True))
    # _active -> active, _latest -> draft (inaktiv) => has_draft_changes True
    db = fake_session(result(active), result(draft))
    out = await SiteConfigService(db).get()
    assert out.version == 3
    assert out.has_draft_changes is True
    assert out.draft.app_name == "Draft"


async def test_get_draft_without_active_version() -> None:
    # active None, latest inaktiv -> version 0, draft = latest branding
    draft = _scv(1, active=False)
    db = fake_session(result(), result(draft))
    out = await SiteConfigService(db).get()
    assert out.version == 0
    assert out.has_draft_changes is True


async def test_put_draft_inplace_update_existing_draft() -> None:
    # latest inaktiv -> in-place Update, kein add
    draft = _scv(2, active=False)
    db = fake_session(
        result(draft),  # _latest
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        # nach commit ruft get() erneut _active + _latest:
        result(),  # get._active -> None
        result(draft),  # get._latest -> draft (inaktiv)
    )
    svc = SiteConfigService(db)
    out = await svc.put_draft(Branding(appName="Neu"), "admin")
    # in-place Update -> kein neuer SiteConfigVersion-Row (nur der Audit-Eintrag).
    assert not any(isinstance(o, SiteConfigVersion) for o in db.added)
    assert draft.branding["appName"] == "Neu"
    assert db.committed == 1
    assert out.has_draft_changes is True


async def test_put_draft_creates_new_version_above_active() -> None:
    active = _scv(5, active=True)
    db = fake_session(
        result(active),  # _latest -> aktiv => neuer Draft
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        result(active),  # get._active
        # get._latest -> der neu angelegte Draft (wir liefern den added-row über Queue):
    )
    _id_on_flush(db)
    svc = SiteConfigService(db)
    out = await svc.put_draft(Branding(appName="Brandneu"), "admin")
    # neuer Row angelegt mit version base+1, inaktiv
    new_rows = [o for o in db.added if isinstance(o, SiteConfigVersion)]
    assert len(new_rows) == 1
    new_row = new_rows[0]
    assert new_row.version == 6
    assert new_row.active is False
    assert db.committed == 1
    # get._latest: kein weiterer Eintrag in Queue -> None => latest None Zweig
    assert out.version == 5


async def test_put_draft_no_versions_creates_version_1() -> None:
    db = fake_session(
        result(),  # _latest -> None => base 0
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        result(),  # get._active -> None
        result(),  # get._latest -> None
    )
    _id_on_flush(db)
    svc = SiteConfigService(db)
    await svc.put_draft(Branding(appName="First"), "admin")
    new_rows = [o for o in db.added if isinstance(o, SiteConfigVersion)]
    assert new_rows[0].version == 1


async def test_activate_conflict_when_no_draft_none() -> None:
    db = fake_session(result())  # _latest -> None
    with pytest.raises(ConflictError, match="no pending"):
        await SiteConfigService(db).activate("admin")


async def test_activate_conflict_when_latest_active() -> None:
    active = _scv(2, active=True)
    db = fake_session(result(active))  # _latest aktiv -> nichts zu aktivieren
    with pytest.raises(ConflictError):
        await SiteConfigService(db).activate("admin")


async def test_activate_promotes_draft() -> None:
    draft = _scv(7, active=False)
    db = fake_session(
        result(draft),  # _latest
        result(),  # execute(update active=False)
        result(),  # config_revision: advisory lock (#config-versioning)
        result(),  # config_revision: head (scalar → None)
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        result(draft),  # get._active -> draft (jetzt aktiv)
        result(draft),  # get._latest -> draft (active True Zweig)
    )
    svc = SiteConfigService(db)
    out = await svc.activate("admin")
    assert draft.active is True
    assert db.committed == 1
    assert out.version == 7
    assert out.has_draft_changes is False


async def test_public_with_active_and_without() -> None:
    active = _scv(9, active=True, branding=Branding(appName="P").model_dump(by_alias=True))
    db = fake_session(result(active))
    out = await SiteConfigService(db).public()
    assert out.version == 9
    assert out.branding.app_name == "P"

    db2 = fake_session(result())  # _active -> None
    out2 = await SiteConfigService(db2).public()
    assert out2.version == 0


async def test_manifest_uses_config_names() -> None:
    branding = Branding(appName="  My Platform  ", appShortName="  MP  ")
    active = _scv(1, active=True, branding=branding.model_dump(by_alias=True))
    db = fake_session(result(active))
    man = await SiteConfigService(db).manifest()
    assert man["name"] == "My Platform"
    assert man["short_name"] == "MP"
    # statische Felder gemerged
    assert man["display"] == "standalone"
    assert "icons" in man


async def test_manifest_falls_back_to_defaults_when_blank() -> None:
    # leere/whitespace Namen -> Defaults
    branding = Branding(appName="   ", appShortName="")
    active = _scv(1, active=True, branding=branding.model_dump(by_alias=True))
    db = fake_session(result(active))
    man = await SiteConfigService(db).manifest()
    assert man["name"] == DEFAULT_APP_NAME
    assert man["short_name"] == DEFAULT_APP_SHORT_NAME


async def test_manifest_no_active_config_uses_defaults() -> None:
    db = fake_session(result())  # _active -> None
    man = await SiteConfigService(db).manifest()
    assert man["name"] == DEFAULT_APP_NAME
    assert man["short_name"] == DEFAULT_APP_SHORT_NAME


def test_module_constants_consistency() -> None:
    # Sicherstellen, dass die forcierten Default-Perms-Map dem Katalog folgen.
    assert set(gr.FORCED_ROLE_DEFAULT_PERMS) == set(FORCED_ROLE_KEYS)
    for perms in gr.FORCED_ROLE_DEFAULT_PERMS.values():
        assert all(p in GREMIUM_PERMISSIONS for p in perms)
