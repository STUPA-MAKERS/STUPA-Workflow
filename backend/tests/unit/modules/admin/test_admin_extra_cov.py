"""Unit tests without a DB: full coverage of Gremium roles and the site-config service.

These tests add the service branches that the other suites leave open. They cover the
Gremium role CRUD with its conflict, not-found, forced-role and in-use blocks. They cover
the idempotent forced-role backfill and the membership validation. They cover the pure
helpers ``_iso``, ``_sanitize_perms`` and ``_role_out``. They also cover
the site-config read, save, public and manifest paths with the fallback names.

These tests need no DB. ``tests._support.auth_fakes.FakeSession`` serves prefilled result
queues and ``get`` queues. Every audit ``record`` runs two ``execute`` calls: the
advisory lock and the prev-hash select. So each audit write needs two ``result()``
entries in the queue.
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
    _role_out,
    _sanitize_perms,
    active_gremium_roles,
    gremium_ids_with_permission,
    gremium_member_ids,
)
from app.modules.admin.models import GremiumMembership, GremiumRole, SiteConfigVersion
from app.modules.admin.schemas import (
    GremiumRoleCreate,
    GremiumRoleUpdate,
)
from app.modules.admin.site_config_service import (
    DEFAULT_APP_NAME,
    DEFAULT_APP_SHORT_NAME,
    SiteConfigService,
    _branding,
)
from app.modules.audit.actions import AuditAction
from app.shared.errors import ConflictError, NotFoundError
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
    """Give every added object an id because the fake ``flush`` sets no primary key."""
    orig_flush = db.flush

    async def _flush() -> None:
        for o in db.added:
            if getattr(o, "id", None) is None:
                o.id = uuid4()
        await orig_flush()

    db.flush = _flush


def test_sanitize_perms() -> None:
    assert _sanitize_perms(None) == []
    # The helper drops a duplicate and an unknown key, then keeps the catalog order.
    out = _sanitize_perms(["vote.cast", "bogus", "session.manage", "vote.cast"])
    assert out == [p for p in GREMIUM_PERMISSIONS if p in {"vote.cast", "session.manage"}]
    assert "bogus" not in out


def test_role_out_forced_flag_and_empty_name() -> None:
    forced = _role(key=next(iter(FORCED_ROLE_KEYS)))
    out = _role_out(forced)
    assert out.forced is True
    r = GremiumRole(gremium_id=uuid4(), key="custom", name_i18n=None, permissions=None)
    r.id = uuid4()
    out2 = _role_out(r)
    assert out2.forced is False
    assert out2.name == {}
    assert out2.permissions == []


async def test_active_gremium_roles_and_permission_helpers() -> None:
    gid = uuid4()
    role = _role(gid, key="vorstand", perms=["session.manage", "vote.cast"])
    # active_gremium_roles: execute returns rows of (gremium_id, role).
    db = fake_session(result((gid, role)))
    pairs = await active_gremium_roles(db, "sub-1", now=_dt("2026-06-01"))
    assert pairs == [(gid, role)]

    db2 = fake_session(result((gid, role)))
    assert await gremium_ids_with_permission(db2, "sub-1", "session.manage") == {gid}
    db3 = fake_session(result((gid, role)))
    assert await gremium_ids_with_permission(db3, "sub-1", "protocol.write") == set()
    # A role with permissions None must not match.
    role_none = _role(gid, key="x", perms=None)
    role_none.permissions = cast("list[str]", None)
    db4 = fake_session(result((gid, role_none)))
    assert await gremium_ids_with_permission(db4, "sub-1", "vote.cast") == set()

    db5 = fake_session(result((gid, role)))
    assert await gremium_member_ids(db5, "sub-1") == {gid}


async def test_active_gremium_roles_default_now() -> None:
    db = fake_session(result())
    assert await active_gremium_roles(db, "nobody") == []


async def test_ensure_forced_roles_adds_when_missing() -> None:
    gid = uuid4()
    db = fake_session(result())  # scalars(present keys) -> empty
    svc = GremiumRoleService(db)
    added = await svc.ensure_forced_roles(gid)
    assert added is True
    assert len(db.added) == 3
    assert db.flushed == 1
    assert {o.key for o in db.added} == set(FORCED_ROLE_KEYS)


async def test_ensure_forced_roles_idempotent_when_all_present() -> None:
    gid = uuid4()
    db = fake_session(result(*FORCED_ROLE_KEYS))  # every key already exists
    svc = GremiumRoleService(db)
    added = await svc.ensure_forced_roles(gid)
    assert added is False
    assert db.added == []
    assert db.flushed == 0


async def test_list_roles_backfills_then_commits() -> None:
    gid = uuid4()
    # 1) ensure_forced_roles scalars(present) -> empty, so it adds and commits.
    # 2) scalars(rows) -> the roles that now exist.
    r1 = _role(gid, key="vorstand")
    db = fake_session(result(), result(r1))
    svc = GremiumRoleService(db)
    out = await svc.list_roles(gid)
    assert db.committed == 1  # because the backfill added a role
    assert [o.key for o in out] == ["vorstand"]


async def test_list_roles_no_backfill_no_commit() -> None:
    gid = uuid4()
    r1 = _role(gid, key="manager")
    # The present keys cover every forced role, so the service adds nothing and commits nothing.
    db = fake_session(result(*FORCED_ROLE_KEYS), result(r1))
    svc = GremiumRoleService(db)
    out = await svc.list_roles(gid)
    assert db.committed == 0
    assert len(out) == 1


async def test_create_role_conflict_on_duplicate_key() -> None:
    gid = uuid4()
    existing = _role(gid, key="reviewer")
    db = fake_session(result(existing))  # scalars(existing) -> first() is not None
    svc = GremiumRoleService(db)
    with pytest.raises(ConflictError):
        await svc.create_role(gid, GremiumRoleCreate(key="reviewer"), "admin")


async def test_create_role_success_sanitizes_perms() -> None:
    gid = uuid4()
    db = fake_session(
        result(),  # scalars(existing) -> none
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
    # The service adds exactly one GremiumRole. The audit row is also in db.added.
    assert sum(isinstance(o, GremiumRole) for o in db.added) == 1


async def test_update_role_not_found() -> None:
    db = fake_session(gets=[None])
    svc = GremiumRoleService(db)
    with pytest.raises(NotFoundError):
        await svc.update_role(uuid4(), GremiumRoleUpdate(name={"de": "X"}), "admin")


async def test_update_role_updates_name_and_perms() -> None:
    role = _role(key="custom", perms=["vote.cast"])
    db = fake_session(result(), result(), gets=[role])  # audit runs execute twice
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
    # name None and permissions None skip both update branches.
    out = await svc.update_role(role.id, GremiumRoleUpdate(), "admin")
    assert out.name == {"de": "Alt"}
    assert out.permissions == ["vote.cast"]


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
    db = fake_session(result(uuid4()), gets=[role])  # scalars(in_use) -> first() is not None
    svc = GremiumRoleService(db)
    with pytest.raises(ConflictError, match="in use"):
        await svc.delete_role(role.id, "admin")


async def test_delete_role_success() -> None:
    role = _role(key="custom")
    db = fake_session(
        result(),  # scalars(in_use) -> empty
        result(),  # scalars(mapped) -> empty
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        gets=[role],
    )
    svc = GremiumRoleService(db)
    await svc.delete_role(role.id, "admin")
    assert role in db.deleted
    assert db.committed == 1


async def test_list_memberships() -> None:
    gid, pid, other = uuid4(), uuid4(), uuid4()
    m = _membership(pid, gid, _dt("2020-01-01"), None)
    # A row without a principal row (outer join) gives no name and no e-mail.
    n = _membership(other, gid, _dt("2020-01-01"), None)
    db = fake_session(result((m, "Max", "max@example.org", True), (n, None, None, None)))
    svc = GremiumRoleService(db)
    out = await svc.list_memberships(gid)
    assert len(out) == 2
    assert out[0].principal_id == pid and out[0].gremium_id == gid
    assert out[0].display_name == "Max" and out[0].email == "max@example.org"
    assert out[0].active is True
    assert out[1].display_name is None and out[1].email is None
    assert out[1].active is False
    dumped = out[0].model_dump(by_alias=True)
    assert dumped["displayName"] == "Max" and dumped["email"] == "max@example.org"
    assert dumped["active"] is True


async def test_list_memberships_marks_inactive_rows() -> None:
    """A deactivated principal or a membership outside its dates is not active."""
    gid = uuid4()
    expired = _membership(uuid4(), gid, _dt("2020-01-01"), _dt("2020-12-31"))
    future = _membership(uuid4(), gid, _dt("2999-01-01"), None)
    deactivated = _membership(uuid4(), gid, None, None)
    current = _membership(uuid4(), gid, None, None)
    db = fake_session(
        result(
            (expired, "A", None, True),
            (future, "B", None, True),
            (deactivated, "C", None, False),
            (current, "D", None, True),
        )
    )
    out = await GremiumRoleService(db).list_memberships(gid)
    assert [r.active for r in out] == [False, False, False, True]


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
    # _active -> None gives version 0 and the default branding.
    db = fake_session(result())
    out = await SiteConfigService(db).get()
    assert out.version == 0
    assert out.branding == Branding()


async def test_get_reads_the_active_version() -> None:
    active = _scv(3, active=True, branding=Branding(appName="Aktiv").model_dump(by_alias=True))
    db = fake_session(result(active))
    out = await SiteConfigService(db).get()
    assert out.version == 3
    assert out.branding.app_name == "Aktiv"


async def test_save_writes_a_new_active_version(
    revisions: list[dict[str, object]],
) -> None:
    active = _scv(5, active=True, branding=Branding(appName="Alt").model_dump(by_alias=True))
    db = fake_session(
        result(active),  # _latest
        result(active),  # _active -> the source of help and tickets
        result(),  # execute(update active=False)
        result(active),  # get._active
    )
    _id_on_flush(db)
    await SiteConfigService(db).save(Branding(appName="Neu", accentColor="#0075BF"), "admin")
    (row,) = [o for o in db.added if isinstance(o, SiteConfigVersion)]
    assert (row.version, row.active) == (6, True)
    assert row.branding["appName"] == "Neu"
    assert row.branding["accentColor"] == "#0075bf"
    assert db.committed == 1
    (rev,) = revisions
    assert rev["action"] == AuditAction.CONFIG_ACTIVATION
    assert rev["extra_data"] == {"siteConfigVersion": 6}


def test_branding_accent_color_shape() -> None:
    assert Branding().accent_color is None
    assert Branding(accentColor="#AbCdEf").accent_color == "#abcdef"
    for bad in ("72a384", "#72a38", "#72a3845", "red", "#ggg000"):
        with pytest.raises(ValueError):
            Branding(accentColor=bad)


async def test_public_with_active_and_without() -> None:
    active = _scv(9, active=True, branding=Branding(appName="P").model_dump(by_alias=True))
    db = fake_session(result(active))
    out = await SiteConfigService(db).public()
    assert out.version == 9
    assert out.branding.app_name == "P"
    # Without a settings row the guest defaults apply: links without an expiry.
    assert out.link_ttl_days is None
    # The upload limits of the wizard come from the settings.
    limits = out.model_dump(by_alias=True)["attachmentLimits"]
    assert limits == {
        "maxFileBytes": 10 * 1024 * 1024,
        "maxDraftFiles": 20,
        "maxDraftBytes": 50 * 1024 * 1024,
    }

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
    # The manifest also merges in the static fields.
    assert man["display"] == "standalone"
    assert man["id"] == "/"
    assert "icons" in man
    assert man["theme_color"] == man["background_color"] == "#e6e9e5"


async def test_manifest_has_the_shortcuts_and_opens_links_in_the_running_app() -> None:
    db = fake_session(result())
    man = await SiteConfigService(db).manifest()
    assert [(s["name"], s["url"]) for s in man["shortcuts"]] == [
        ("Neuer Antrag", "apply"),
        ("Meine To-Dos", "todos"),
        ("Sitzungen", "meetings"),
    ]
    for shortcut in man["shortcuts"]:
        assert shortcut["icons"] == [
            {"src": "icons/icon-96x96.png", "sizes": "96x96", "type": "image/png"}
        ]
    assert man["launch_handler"] == {"client_mode": ["navigate-existing", "auto"]}


async def test_manifest_dark_scheme_takes_the_dark_bar_colours() -> None:
    active = _scv(1, active=True, branding=Branding().model_dump(by_alias=True))
    db = fake_session(result(active))
    man = await SiteConfigService(db).manifest("dark")
    assert man["theme_color"] == man["background_color"] == "#262a27"


async def test_manifest_falls_back_to_defaults_when_blank() -> None:
    # An empty or whitespace name falls back to the default.
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


async def test_manifest_colours_are_the_bottom_bar_surface() -> None:
    # Chrome paints the navigation bar of the installed app with theme_color or
    # background_color, depending on the version, so both take the bottom bar surface.
    db = fake_session(result())
    man = await SiteConfigService(db).manifest()
    assert man["theme_color"] == man["background_color"] == "#e6e9e5"


def test_module_constants_consistency() -> None:
    assert set(gr.FORCED_ROLE_DEFAULT_PERMS) == set(FORCED_ROLE_KEYS)
    for perms in gr.FORCED_ROLE_DEFAULT_PERMS.values():
        assert all(p in GREMIUM_PERMISSIONS for p in perms)


# -- help & tickets ("Hilfe & Tickets") ----------------------------------------------


def test_public_branding_hides_the_help_and_ticket_settings() -> None:
    from app.modules.admin.branding import HelpSettings, PublicBranding

    with pytest.raises(ValueError, match="https://"):
        HelpSettings(wikiUrl="javascript:alert(1)")
    assert HelpSettings(wikiUrl="  http://wiki.example.org  ").wiki_url == (
        "http://wiki.example.org"
    )
    dumped = PublicBranding().model_dump(by_alias=True)
    assert "help" not in dumped
    assert "tickets" not in dumped
    full = Branding().model_dump(by_alias=True)
    assert full["help"]["wikiUrl"].startswith("https://wiki.reutlingen.university/")
    assert full["tickets"] == {"publicEnabled": True, "notifyNew": True, "retentionMonths": 12}


async def test_public_names_the_wiki_and_the_public_switch() -> None:
    branding = Branding.model_validate(
        {"tickets": {"publicEnabled": False}, "help": {"wikiUrl": "https://w.example.org"}}
    )
    active = _scv(2, active=True, branding=branding.model_dump(by_alias=True))
    out = (await SiteConfigService(fake_session(result(active))).public()).model_dump(by_alias=True)
    assert out["help"] == {"wikiUrl": "https://w.example.org"}
    assert out["tickets"] == {"publicEnabled": False}
    assert "help" not in out["branding"]
    assert "tickets" not in out["branding"]


async def test_active_branding_reads_the_active_row_or_the_defaults() -> None:
    from app.modules.admin.site_config_service import active_branding

    active = _scv(1, active=True, branding=Branding(appName="A").model_dump(by_alias=True))
    assert (await active_branding(fake_session(result(active)))).app_name == "A"
    assert (await active_branding(fake_session(result()))).tickets.retention_months == 12


async def test_help_tickets_reads_the_active_settings() -> None:
    branding = Branding.model_validate({"tickets": {"retentionMonths": None, "notifyNew": False}})
    active = _scv(1, active=True, branding=branding.model_dump(by_alias=True))
    out = await SiteConfigService(fake_session(result(active))).help_tickets()
    assert out.model_dump(by_alias=True) == {
        "wikiUrl": "https://wiki.reutlingen.university/books/antragsplattform",
        "publicEnabled": True,
        "notifyNew": False,
        "retentionMonths": None,
    }


@pytest.fixture
def revisions(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    from app.modules.admin import site_config_service as scs

    recorded: list[dict[str, object]] = []

    class _Revisions:
        def __init__(self, _session: object) -> None:
            pass

        async def record(self, **kw: object) -> None:
            recorded.append(kw)

    monkeypatch.setattr(scs, "ConfigRevisionService", _Revisions)
    return recorded


def _settings(**kw: object):
    from app.modules.admin.schemas import HelpTicketsSettings

    return HelpTicketsSettings.model_validate(
        {
            "wikiUrl": "https://w.example.org",
            "publicEnabled": False,
            "notifyNew": False,
            "retentionMonths": 6,
            **kw,
        }
    )


async def test_put_help_tickets_writes_a_new_active_version(
    revisions: list[dict[str, object]],
) -> None:
    active = _scv(4, active=True, branding=Branding(appName="Keep").model_dump(by_alias=True))
    db = fake_session(result(active), result(active), result())
    out = await SiteConfigService(db).put_help_tickets(_settings(), "admin")
    assert out.retention_months == 6
    (row,) = [o for o in db.added if isinstance(o, SiteConfigVersion)]
    assert (row.version, row.active) == (5, True)
    assert row.branding["appName"] == "Keep"
    assert row.branding["tickets"]["publicEnabled"] is False
    assert db.committed == 1
    (rev,) = revisions
    assert rev["extra_data"] == {"siteConfigVersion": 5, "section": "helpTickets"}


async def test_put_help_tickets_on_an_empty_database(
    revisions: list[dict[str, object]],
) -> None:
    db = fake_session(result(), result(), result())
    await SiteConfigService(db).put_help_tickets(_settings(), "admin")
    (row,) = [o for o in db.added if isinstance(o, SiteConfigVersion)]
    assert row.version == 1


def test_help_tickets_settings_validate_url_and_months() -> None:
    with pytest.raises(ValueError):
        _settings(wikiUrl="ftp://x")
    with pytest.raises(ValueError):
        _settings(retentionMonths=0)
    with pytest.raises(ValueError):
        _settings(retentionMonths=121)
    with pytest.raises(ValueError):
        _settings(extra=1)
