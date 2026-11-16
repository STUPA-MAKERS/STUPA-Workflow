"""Integration tests for the Alembic migrations and DB constraints on a real Postgres 16.

Upgrade and downgrade run clean. The partial unique indexes for the
active form version and the initial state hold. The GIN index exists. The seed creates
the default roles. A deleted application cascades to its applicant rows.
"""

from __future__ import annotations

import json
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


def _new_type(conn) -> str:
    return conn.execute(
        text("INSERT INTO application_type (key) VALUES (:k) RETURNING id"),
        {"k": "t-" + str(conn.execute(text("SELECT gen_random_uuid()")).scalar())},
    ).scalar_one()


def test_upgrade_and_downgrade_clean(alembic_cfg: Config, engine: Engine) -> None:
    """Run the round trip head, base, head; the fixture already upgraded to head."""
    command.downgrade(alembic_cfg, "base")
    with engine.connect() as conn:
        remaining = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='application'"
            )
        ).scalar_one()
    assert remaining == 0
    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM application")).scalar_one() == 0


def test_seed_default_roles(engine: Engine) -> None:
    with engine.connect() as conn:
        keys = {
            r[0]
            for r in conn.execute(text("SELECT key FROM role")).fetchall()
        }
        admin_perms = conn.execute(
            text(
                "SELECT count(*) FROM role_permission rp JOIN role r ON r.id=rp.role_id "
                "WHERE r.key='admin'"
            )
        ).scalar_one()
    assert {"admin", "member", "manager", "protocol", "finance"} <= keys
    assert admin_perms >= 10


def test_partial_unique_one_active_form_version(engine: Engine) -> None:
    with engine.begin() as conn:
        type_id = _new_type(conn)
        conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version, active) "
                "VALUES (:t, 1, true)"
            ),
            {"t": type_id},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version, active) "
                "VALUES (:t, 2, true)"
            ),
            {"t": type_id},
        )


def test_partial_unique_one_initial_state(engine: Engine) -> None:
    with engine.begin() as conn:
        fv = conn.execute(
            text(
                "INSERT INTO flow_version (version) "
                "VALUES (1) RETURNING id"
            ),
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO state (flow_version_id, key, is_initial) "
                "VALUES (:f, 'a', true)"
            ),
            {"f": fv},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO state (flow_version_id, key, is_initial) "
                "VALUES (:f, 'b', true)"
            ),
            {"f": fv},
        )


def test_state_color_column(engine: Engine) -> None:
    with engine.begin() as conn:
        fv = conn.execute(
            text(
                "INSERT INTO flow_version (version) "
                "VALUES (1) RETURNING id"
            ),
        ).scalar_one()
        color = conn.execute(
            text(
                "INSERT INTO state (flow_version_id, key, color) "
                "VALUES (:f, 'x', '#4a90d9') RETURNING color"
            ),
            {"f": fv},
        ).scalar_one()
    assert color == "#4a90d9"


def test_gin_index_on_application_data(engine: Engine) -> None:
    with engine.connect() as conn:
        indexdef = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname='ix_application_data'")
        ).scalar_one()
    assert "gin" in indexdef.lower()
    assert "jsonb_path_ops" in indexdef


def test_applicant_cascade_on_application_delete(engine: Engine) -> None:
    with engine.begin() as conn:
        type_id = _new_type(conn)
        fv = conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
        ).scalar_one()
        flv = conn.execute(
            text(
                "INSERT INTO flow_version (version) "
                "VALUES (1) RETURNING id"
            ),
        ).scalar_one()
        app_id = conn.execute(
            text(
                "INSERT INTO application (type_id, form_version_id, flow_version_id) "
                "VALUES (:t, :fv, :flv) RETURNING id"
            ),
            {"t": type_id, "fv": fv, "flv": flv},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO applicant (application_id, email) "
                "VALUES (:a, 'x@example.org')"
            ),
            {"a": app_id},
        )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM application WHERE id=:a"), {"a": app_id})
    with engine.connect() as conn:
        left = conn.execute(text("SELECT count(*) FROM applicant")).scalar_one()
    assert left == 0


def test_citext_email_case_insensitive(engine: Engine) -> None:
    with engine.begin() as conn:
        type_id = _new_type(conn)
        fv = conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
        ).scalar_one()
        flv = conn.execute(
            text(
                "INSERT INTO flow_version (version) "
                "VALUES (1) RETURNING id"
            ),
        ).scalar_one()
        app_id = conn.execute(
            text(
                "INSERT INTO application (type_id, form_version_id, flow_version_id) "
                "VALUES (:t, :fv, :flv) RETURNING id"
            ),
            {"t": type_id, "fv": fv, "flv": flv},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO applicant (application_id, email) VALUES (:a, 'Foo@Bar.DE')"),
            {"a": app_id},
        )
    with engine.connect() as conn:
        hit = conn.execute(
            text("SELECT count(*) FROM applicant WHERE email = 'foo@bar.de'")
        ).scalar_one()
    assert hit == 1


def test_drop_type_flows_repairs_legacy_duplicates(engine: Engine) -> None:
    """Migration 0019 repairs legacy data from the per-type era.

    The migration repairs several active flows and duplicate version numbers. It does
    not fail on the partial unique index. The global flow (application_type_id IS NULL)
    stays the active one.
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0019_drop_type_flows.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0019", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS uq_flow_version_one_active_global"))
        conn.execute(
            text(
                "ALTER TABLE flow_version "
                "DROP CONSTRAINT IF EXISTS flow_version_version_key"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE flow_version "
                "DROP CONSTRAINT IF EXISTS uq_flow_version_version"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE flow_version "
                "ADD COLUMN IF NOT EXISTS application_type_id uuid"
            )
        )
        type_id = _new_type(conn)
        conn.execute(
            text(
                "INSERT INTO flow_version (version, active, application_type_id) "
                "VALUES (1, true, :t), (2, false, NULL)"
            ),
            {"t": type_id},
        )
        global_id = conn.execute(
            text(
                "INSERT INTO flow_version (version, active, application_type_id) "
                "VALUES (1, true, NULL) RETURNING id"
            )
        ).scalar_one()

    with engine.begin() as conn:
        for stmt in mod._UPGRADE:
            conn.execute(text(stmt))

    with engine.connect() as conn:
        actives = conn.execute(
            text("SELECT id FROM flow_version WHERE active")
        ).scalars().all()
        versions = sorted(
            conn.execute(text("SELECT version FROM flow_version")).scalars()
        )
        has_type_col = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'flow_version' "
                "AND column_name = 'application_type_id')"
            )
        ).scalar_one()
    assert actives == [global_id]
    assert versions == [1, 2, 3]
    assert has_type_col is False


def test_split_oidc_mappings_converts_gremium_group_mappings(
    alembic_cfg: Config, engine: Engine
) -> None:
    """Migration 14ed7a68a641 splits one gremium group mapping into two links.

    The group becomes a member of the gremium. It keeps its role through a role mapping,
    unless the role is the forced `member`. A global mapping with a gremium scope goes.
    """
    command.downgrade(alembic_cfg, "097f61e33e3c")
    with engine.begin() as conn:
        gid = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', 'g-split') RETURNING id")
        ).scalar_one()
        member, board = (
            conn.execute(
                text(
                    "INSERT INTO gremium_role (gremium_id, key) VALUES (:g, :k) RETURNING id"
                ),
                {"g": gid, "k": key},
            ).scalar_one()
            for key in ("member", "vorstand")
        )
        conn.execute(
            text(
                "INSERT INTO gremium_group_mapping (gremium_id, gremium_role_id, oidc_group) "
                "VALUES (:g, :m, 'g-members'), (:g, :b, 'g-board')"
            ),
            {"g": gid, "m": member, "b": board},
        )
        role = conn.execute(text("SELECT id FROM role WHERE key = 'member'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO group_mapping (oidc_group, role_id, gremium_id) "
                "VALUES ('global', :r, NULL), ('scoped', :r, :g)"
            ),
            {"r": role, "g": gid},
        )

    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        memberships = conn.execute(
            text("SELECT oidc_group FROM gremium_membership_mapping WHERE gremium_id = :g"),
            {"g": gid},
        ).scalars().all()
        roles = conn.execute(
            text("SELECT gremium_role_id, oidc_group FROM gremium_role_mapping")
        ).all()
        globals_ = conn.execute(text("SELECT oidc_group FROM group_mapping")).scalars().all()
        old = conn.execute(text("SELECT to_regclass('gremium_group_mapping')")).scalar_one()
    assert sorted(memberships) == ["g-board", "g-members"]
    assert [(r[0], r[1]) for r in roles] == [(board, "g-board")]
    assert globals_ == ["global"]
    assert old is None


def test_drop_global_meeting_permissions(alembic_cfg: Config, engine: Engine) -> None:
    """Migration 3a0b9672fcba drops the superseded global meeting keys.

    The upgrade gives `protocol.finalize` to the forced gremium roles `vorstand` and
    `manager` only, and deletes the three global keys from every role. The downgrade
    restores the seed grants and takes `protocol.finalize` off every gremium role.

    The test stops at 3a0b9672fcba, because b0c8fd389e10 also gives the key to ``schrift``.
    The downgrade is lossy by design: a custom role does not get its key back. A second
    upgrade adds the key exactly once.
    """
    command.downgrade(alembic_cfg, "14ed7a68a641")
    with engine.begin() as conn:
        gid = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', 'g-drop-meet') RETURNING id")
        ).scalar_one()
        for key, perms in (
            ("vorstand", '["session.manage", "protocol.write"]'),
            ("manager", '["session.manage"]'),
            ("member", '["vote.cast"]'),
            ("schrift", '["session.manage", "protocol.write"]'),
        ):
            conn.execute(
                text(
                    "INSERT INTO gremium_role (gremium_id, key, permissions) "
                    "VALUES (:g, :k, CAST(:p AS jsonb))"
                ),
                {"g": gid, "k": key, "p": perms},
            )
        custom = conn.execute(
            text("INSERT INTO role (key) VALUES ('sitzungsdienst') RETURNING id")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO role_permission (role_id, permission) VALUES "
                "(:r, 'meeting.manage'), (:r, 'application.read')"
            ),
            {"r": custom},
        )

    def _gremium_perms(conn) -> dict[str, list[str]]:
        rows = conn.execute(
            text("SELECT key, permissions FROM gremium_role WHERE gremium_id = :g"),
            {"g": gid},
        ).all()
        return {r[0]: list(r[1]) for r in rows}

    def _dropped(conn) -> list[tuple[str, str]]:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT r.key, rp.permission FROM role_permission rp "
                    "JOIN role r ON r.id = rp.role_id WHERE rp.permission IN "
                    "('meeting.manage', 'protocol.finalize', 'application.create') "
                    "ORDER BY r.key, rp.permission"
                )
            ).all()
        ]

    command.upgrade(alembic_cfg, "3a0b9672fcba")
    with engine.connect() as conn:
        perms = _gremium_perms(conn)
        dropped = _dropped(conn)
        kept = conn.execute(
            text("SELECT permission FROM role_permission WHERE role_id = :r"), {"r": custom}
        ).scalars().all()
    assert "protocol.finalize" in perms["vorstand"]
    assert "protocol.finalize" in perms["manager"]
    assert "protocol.finalize" not in perms["member"]
    assert "protocol.finalize" not in perms["schrift"]
    assert dropped == []
    assert kept == ["application.read"]

    command.downgrade(alembic_cfg, "14ed7a68a641")
    with engine.connect() as conn:
        perms = _gremium_perms(conn)
        restored = _dropped(conn)
    assert all("protocol.finalize" not in p for p in perms.values())
    assert ("manager", "meeting.manage") in restored
    assert ("admin", "protocol.finalize") in restored
    assert ("protocol", "meeting.manage") in restored
    assert all(key != "sitzungsdienst" for key, _ in restored)

    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        perms = _gremium_perms(conn)
    assert perms["vorstand"].count("protocol.finalize") == 1


def test_drop_global_vote_permissions(
    alembic_cfg: Config, engine: Engine, capfd: pytest.CaptureFixture[str]
) -> None:
    """Migration b0c8fd389e10 drops the global `vote.cast` and `vote.manage`.

    The upgrade reports the votes without a gremium as eligible group and the
    application votes of another gremium, and keeps them. It deletes the two keys
    from every global role, and gives `protocol.finalize` to each gremium role with
    `session.manage`. The downgrade restores the seed grants of 0002 and keeps
    `protocol.finalize`.

    The report is read from stderr, because ``env.py`` runs ``fileConfig``, which resets the
    handlers of the alembic loggers, and the console handler of ``alembic.ini`` writes to
    stderr. ``head`` also runs the to-do migration, which grants ``todo.write`` to every
    gremium role, so the comparison leaves the to-do grants out and checks them on their
    own.
    """
    command.downgrade(alembic_cfg, "3a0b9672fcba")
    with engine.begin() as conn:
        gid = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', 'g-drop-vote') RETURNING id")
        ).scalar_one()
        for key, perms in (
            ("sitzungsleitung", '["session.manage", "protocol.write"]'),
            ("schrift", '["protocol.write"]'),
            ("vorsitz", '["session.manage", "protocol.finalize"]'),
        ):
            conn.execute(
                text(
                    "INSERT INTO gremium_role (gremium_id, key, permissions) "
                    "VALUES (:g, :k, CAST(:p AS jsonb))"
                ),
                {"g": gid, "k": key, "p": perms},
            )
        other = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('O', 'o-drop-vote') RETURNING id")
        ).scalar_one()
        type_id = _new_type(conn)
        fv = conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
        ).scalar_one()
        flv = conn.execute(
            text("INSERT INTO flow_version (version) VALUES (1) RETURNING id")
        ).scalar_one()
        app_id = conn.execute(
            text(
                "INSERT INTO application (type_id, form_version_id, flow_version_id, "
                "gremium_id) VALUES (:t, :fv, :flv, :g) RETURNING id"
            ),
            {"t": type_id, "fv": fv, "flv": flv, "g": gid},
        ).scalar_one()
        free_vote = conn.execute(
            text(
                "INSERT INTO vote (eligible_group, config, status) "
                "VALUES ('stupa', '{}'::jsonb, 'closed') RETURNING id"
            )
        ).scalar_one()
        foreign_vote = conn.execute(
            text(
                "INSERT INTO vote (application_id, eligible_group, config, status) "
                "VALUES (:a, :g, '{}'::jsonb, 'draft') RETURNING id"
            ),
            {"a": app_id, "g": str(other)},
        ).scalar_one()
        good_vote = conn.execute(
            text(
                "INSERT INTO vote (application_id, eligible_group, config, status) "
                "VALUES (:a, :g, '{}'::jsonb, 'draft') RETURNING id"
            ),
            {"a": app_id, "g": str(gid)},
        ).scalar_one()
        custom = conn.execute(
            text("INSERT INTO role (key) VALUES ('wahlleitung') RETURNING id")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO role_permission (role_id, permission) VALUES "
                "(:r, 'vote.manage'), (:r, 'application.read')"
            ),
            {"r": custom},
        )

    def _gremium_perms(conn) -> dict[str, list[str]]:
        rows = conn.execute(
            text("SELECT key, permissions FROM gremium_role WHERE gremium_id = :g"),
            {"g": gid},
        ).all()
        return {r[0]: list(r[1]) for r in rows}

    def _dropped(conn) -> list[tuple[str, str]]:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT r.key, rp.permission FROM role_permission rp "
                    "JOIN role r ON r.id = rp.role_id "
                    "WHERE rp.permission IN ('vote.cast', 'vote.manage') "
                    "ORDER BY r.key, rp.permission"
                )
            ).all()
        ]

    capfd.readouterr()
    command.upgrade(alembic_cfg, "head")
    report = capfd.readouterr().err
    with engine.connect() as conn:
        dropped = _dropped(conn)
        kept = conn.execute(
            text("SELECT permission FROM role_permission WHERE role_id = :r"), {"r": custom}
        ).scalars().all()
        votes = set(conn.execute(text("SELECT id FROM vote")).scalars().all())
        perms = _gremium_perms(conn)
    assert dropped == []
    todo = {"todo.write", "todo.configure"}
    stripped = {key: [p for p in ps if p not in todo] for key, ps in perms.items()}
    assert stripped["sitzungsleitung"] == ["session.manage", "protocol.write", "protocol.finalize"]
    assert stripped["schrift"] == ["protocol.write"]
    assert stripped["vorsitz"] == ["session.manage", "protocol.finalize"]
    assert all("todo.write" in perms[key] for key in ("sitzungsleitung", "schrift", "vorsitz"))
    assert kept == ["application.read"]
    assert {free_vote, foreign_vote, good_vote} <= votes
    assert str(free_vote) in report
    assert str(foreign_vote) in report
    assert str(good_vote) not in report
    assert "'wahlleitung' loses the permission(s): vote.manage" in report

    command.downgrade(alembic_cfg, "3a0b9672fcba")
    with engine.connect() as conn:
        restored = _dropped(conn)
    assert ("admin", "vote.cast") in restored
    assert ("admin", "vote.manage") in restored
    assert ("manager", "vote.manage") in restored
    assert ("member", "vote.cast") in restored
    assert all(key != "wahlleitung" for key, _ in restored)
    with engine.connect() as conn:
        perms = _gremium_perms(conn)
    assert "protocol.finalize" in perms["sitzungsleitung"]

    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        assert _dropped(conn) == []
        perms = _gremium_perms(conn)
    assert perms["sitzungsleitung"].count("protocol.finalize") == 1
    assert perms["vorsitz"].count("protocol.finalize") == 1
    assert "protocol.finalize" not in perms["schrift"]


def test_drop_vote_notification_kind(
    alembic_cfg: Config, engine: Engine, capfd: pytest.CaptureFixture[str]
) -> None:
    """Migration 1a9feecb23a5 drops the dead kinds `vote` and `role_change`.

    The upgrade deletes their preference rows and the stored overrides of the role
    mail templates, and logs each deleted template. It keeps every other row. The
    downgrade changes nothing.

    The test cleans up ``principal`` and ``mail_template`` itself, because they are not in
    the truncate list of the fixture.
    """
    command.downgrade(alembic_cfg, "b0c8fd389e10")
    with engine.begin() as conn:
        pid = conn.execute(
            text("INSERT INTO principal (sub) VALUES (:s) RETURNING id"),
            {"s": f"mig-kind-{uuid.uuid4()}"},
        ).scalar_one()
        for kind in ("vote", "role_change", "comment"):
            conn.execute(
                text(
                    "INSERT INTO notification_preference (principal_id, kind, enabled) "
                    "VALUES (:p, :k, false)"
                ),
                {"p": pid, "k": kind},
            )
        for key in ("role_assigned", "role_revoked", "meeting_created"):
            conn.execute(
                text("INSERT INTO mail_template (key) VALUES (:k) ON CONFLICT DO NOTHING"),
                {"k": key},
            )

    capfd.readouterr()
    command.upgrade(alembic_cfg, "head")
    report = capfd.readouterr().err
    with engine.connect() as conn:
        kinds = set(
            conn.execute(
                text("SELECT kind FROM notification_preference WHERE principal_id = :p"),
                {"p": pid},
            ).scalars()
        )
        keys = set(conn.execute(text("SELECT key FROM mail_template")).scalars())
    assert kinds == {"comment"}
    assert "role_assigned" not in keys
    assert "role_revoked" not in keys
    assert "meeting_created" in keys
    assert "'role_assigned'" in report
    assert "'role_revoked'" in report

    command.downgrade(alembic_cfg, "b0c8fd389e10")
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM notification_preference WHERE principal_id = :p"),
            {"p": pid},
        ).scalar_one() == 1
    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM principal WHERE id = :p"), {"p": pid})
        conn.execute(text("DELETE FROM mail_template WHERE key = 'meeting_created'"))


def test_vote_closed_at_backfill_and_allow_change_strip(
    alembic_cfg: Config, engine: Engine, capfd: pytest.CaptureFixture[str]
) -> None:
    """Migration 863a6833fea5 adds `vote.closed_at`.

    The upgrade backfills `closed_at` from the `status_change` audit entry of the result
    branch, at or after the open time, and keeps NULL where the audit log has no such
    entry. It removes `allowChange` from every vote config and reports the meeting
    votes with the result `tie`. The downgrade drops the column.

    Of two status changes of the branch, one before the open (an older vote of the same
    application) and the real one, the backfill takes the first at or after the open time.
    """
    command.downgrade(alembic_cfg, "1a9feecb23a5")
    with engine.begin() as conn:
        type_id = _new_type(conn)
        fv = conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
        ).scalar_one()
        flv = conn.execute(
            text("INSERT INTO flow_version (version) VALUES (1) RETURNING id")
        ).scalar_one()
        voting, approved = (
            conn.execute(
                text(
                    "INSERT INTO state (flow_version_id, key) VALUES (:f, :k) RETURNING id"
                ),
                {"f": flv, "k": key},
            ).scalar_one()
            for key in ("voting", "approved")
        )
        branch = conn.execute(
            text(
                "INSERT INTO transition (flow_version_id, from_state_id, to_state_id, "
                "branch) VALUES (:f, :a, :b, 'pass') RETURNING id"
            ),
            {"f": flv, "a": voting, "b": approved},
        ).scalar_one()
        app_id = conn.execute(
            text(
                "INSERT INTO application (type_id, form_version_id, flow_version_id) "
                "VALUES (:t, :fv, :flv) RETURNING id"
            ),
            {"t": type_id, "fv": fv, "flv": flv},
        ).scalar_one()

        def _vote(status: str, config: str, **cols: object) -> uuid.UUID:
            names = ", ".join(["eligible_group", "config", "status", *cols])
            values = ", ".join([":g", "CAST(:c AS jsonb)", ":s", *(f":{k}" for k in cols)])
            return conn.execute(
                text(f"INSERT INTO vote ({names}) VALUES ({values}) RETURNING id"),
                {"g": "g", "c": config, "s": status, **cols},
            ).scalar_one()

        opened = "2026-06-01 10:00:00+00"
        fired = _vote(
            "closed",
            '{"options": ["yes", "no"], "majorityRule": "simple", "allowChange": false}',
            application_id=app_id,
            result_branch_transition_id=branch,
            opens_at=opened,
            result="passed",
        )
        no_audit = _vote(
            "closed",
            '{"options": ["yes", "no"], "majorityRule": "simple"}',
            application_id=app_id,
            opens_at=opened,
            result="rejected",
        )
        gremium = conn.execute(
            text(
                "INSERT INTO gremium (name, slug) VALUES ('G', :s) RETURNING id"
            ),
            {"s": f"g-closed-at-{uuid.uuid4()}"},
        ).scalar_one()
        meeting = conn.execute(
            text("INSERT INTO meeting (gremium_id, title) VALUES (:g, 'M') RETURNING id"),
            {"g": gremium},
        ).scalar_one()
        tie = _vote(
            "closed",
            '{"options": ["yes", "no"], "majorityRule": "simple", "allowChange": true}',
            meeting_id=meeting,
            result="tie",
        )
        running = _vote("open", '{"options": ["yes", "no"], "majorityRule": "simple"}')
        for at in ("2026-05-01 09:00:00+00", "2026-06-01 10:07:00+00",
                   "2026-06-01 11:00:00+00"):
            conn.execute(
                text(
                    "INSERT INTO audit_entry (actor, action, target_type, target_id, at, "
                    "data, hash) VALUES ('mgr', 'status_change', 'application', :a, "
                    ":at, CAST(:d AS jsonb), '\\x00')"
                ),
                {"a": str(app_id), "at": at,
                 "d": f'{{"transitionId": "{branch}"}}'},
            )

    capfd.readouterr()
    command.upgrade(alembic_cfg, "head")
    report = capfd.readouterr().err
    with engine.connect() as conn:
        rows = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                text("SELECT id, closed_at, config FROM vote")
            ).all()
        }
    closed_at, config = rows[fired]
    assert closed_at is not None
    assert closed_at.isoformat().startswith("2026-06-01T10:07")
    assert "allowChange" not in config
    assert rows[no_audit][0] is None
    assert rows[running][0] is None
    assert "allowChange" not in rows[tie][1]
    assert "1 vote(s) backfilled" in report
    assert "removed allowChange from the config of 2 vote(s)" in report
    assert str(tie) in report and "'tie'" in report

    command.downgrade(alembic_cfg, "1a9feecb23a5")
    with engine.connect() as conn:
        cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'vote' AND column_name = 'closed_at'"
            )
        ).all()
    assert cols == []
    command.upgrade(alembic_cfg, "head")


def _agenda_fk_rule(conn) -> str:
    """Return `confdeltype` of the foreign key on `vote.agenda_item_id` (c, n, ...)."""
    return conn.execute(
        text(
            "SELECT con.confdeltype FROM pg_constraint AS con "
            "JOIN pg_attribute AS att ON att.attrelid = con.conrelid "
            "AND att.attnum = ANY (con.conkey) "
            "WHERE con.conrelid = 'vote'::regclass AND con.contype = 'f' "
            "AND att.attname = 'agenda_item_id'"
        )
    ).scalar_one()


def test_meeting_started_at_and_vote_agenda_fk(
    alembic_cfg: Config, engine: Engine, capfd: pytest.CaptureFixture[str]
) -> None:
    """Migration eff772f93d8e adds `meeting.started_at` and keeps agenda votes.

    The upgrade adds the column without a backfill and logs the live and closed
    meetings that stay NULL. It changes the foreign key `vote.agenda_item_id` from
    CASCADE to SET NULL, so a meeting delete keeps the votes and their ballots. The
    downgrade restores CASCADE and drops the column.
    """
    command.downgrade(alembic_cfg, "863a6833fea5")
    with engine.begin() as conn:
        assert _agenda_fk_rule(conn) == "c"
        gremium = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', :s) RETURNING id"),
            {"s": f"g-started-{uuid.uuid4()}"},
        ).scalar_one()
        meetings = [
            conn.execute(
                text(
                    "INSERT INTO meeting (gremium_id, title, status) "
                    "VALUES (:g, 'M', :s) RETURNING id"
                ),
                {"g": gremium, "s": status},
            ).scalar_one()
            for status in ("planned", "live", "closed")
        ]

    capfd.readouterr()
    command.upgrade(alembic_cfg, "eff772f93d8e")
    report = capfd.readouterr().err
    assert "2 live or closed meeting(s) without a known start stay NULL" in report

    closed = meetings[2]
    with engine.begin() as conn:
        assert _agenda_fk_rule(conn) == "n"
        assert conn.execute(
            text("SELECT count(*) FROM meeting WHERE started_at IS NULL")
        ).scalar_one() == 3
        item = conn.execute(
            text(
                "INSERT INTO meeting_agenda_item (meeting_id, title) "
                "VALUES (:m, 'TOP') RETURNING id"
            ),
            {"m": closed},
        ).scalar_one()
        vote = conn.execute(
            text(
                "INSERT INTO vote (eligible_group, config, status, result, meeting_id, "
                "agenda_item_id) VALUES (:g, CAST(:c AS jsonb), 'closed', 'passed', "
                ":m, :i) RETURNING id"
            ),
            {
                "g": str(gremium),
                "c": '{"options": ["yes", "no"], "majorityRule": "simple"}',
                "m": closed,
                "i": item,
            },
        ).scalar_one()
        conn.execute(
            text("INSERT INTO ballot (vote_id, voter_sub, choice) VALUES (:v, 's', 'yes')"),
            {"v": vote},
        )
        conn.execute(text("DELETE FROM meeting WHERE id = :m"), {"m": closed})
        kept = conn.execute(
            text("SELECT meeting_id, agenda_item_id FROM vote WHERE id = :v"), {"v": vote}
        ).one()
        ballots = conn.execute(
            text("SELECT count(*) FROM ballot WHERE vote_id = :v"), {"v": vote}
        ).scalar_one()
    assert tuple(kept) == (None, None)
    assert ballots == 1

    command.downgrade(alembic_cfg, "863a6833fea5")
    with engine.connect() as conn:
        assert _agenda_fk_rule(conn) == "c"
        cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'meeting' AND column_name = 'started_at'"
            )
        ).all()
    assert cols == []
    command.upgrade(alembic_cfg, "head")


_SEED_MAGIC_LINK_BODY = {
    "de": (
        "Hallo,\n\nüber diesen Link gelangen Sie zu Ihrem Antrag:\n{{ link }}\n\n"
        "Der Link ist zeitlich begrenzt gültig. Wenn Sie das nicht angefordert "
        "haben, ignorieren Sie diese Mail.\n"
    ),
    "en": (
        "Hello,\n\nuse this link to access your application:\n{{ link }}\n\n"
        "The link is valid for a limited time. If you did not request it, "
        "ignore this email.\n"
    ),
}


def test_guest_application_settings_and_unlimited_links(
    alembic_cfg: Config, engine: Engine
) -> None:
    """Migration d5569d5542c6.

    The upgrade creates the settings row (12 hours, no link expiry), makes
    `magic_link.expires_at` nullable and allows NULL only for an edit link. The
    existing links keep their expiry. The downgrade gives a link without an expiry
    seven days, restores NOT NULL and drops the table.

    Another template with the seed text of the magic-link mail stays as it is. The test
    leaves the schema at head, because the teardown truncates
    ``guest_application_settings``.
    """
    command.downgrade(alembic_cfg, "eff772f93d8e")
    with engine.begin() as conn:
        assert conn.execute(
            text("SELECT to_regclass('guest_application_settings')")
        ).scalar_one() is None
        type_id = _new_type(conn)
        fv = conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
        ).scalar_one()
        flv = conn.execute(
            text("INSERT INTO flow_version (version) VALUES (1) RETURNING id")
        ).scalar_one()
        app_id = conn.execute(
            text(
                "INSERT INTO application (type_id, form_version_id, flow_version_id) "
                "VALUES (:t, :fv, :flv) RETURNING id"
            ),
            {"t": type_id, "fv": fv, "flv": flv},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO magic_link (application_id, token_hash, scope, expires_at, "
                "single_use) VALUES (:a, '\\x01', 'view', "
                "'2026-06-01 10:00:00+00', true)"
            ),
            {"a": app_id},
        )
        conn.execute(
            text(
                "INSERT INTO mail_template (key, body_i18n) VALUES ('magic_link', "
                "CAST(:b AS jsonb)) ON CONFLICT (key) DO UPDATE SET body_i18n = "
                "EXCLUDED.body_i18n"
            ),
            {"b": json.dumps(_SEED_MAGIC_LINK_BODY)},
        )
        conn.execute(
            text(
                "INSERT INTO mail_template (key, body_i18n) VALUES ('mig_probe', "
                "CAST(:b AS jsonb)) ON CONFLICT (key) DO UPDATE SET body_i18n = "
                "EXCLUDED.body_i18n"
            ),
            {"b": json.dumps(_SEED_MAGIC_LINK_BODY)},
        )

    command.upgrade(alembic_cfg, "d5569d5542c6")
    with engine.begin() as conn:
        body = conn.execute(
            text("SELECT body_i18n FROM mail_template WHERE key = 'magic_link'")
        ).scalar_one()
        assert "zeitlich begrenzt" not in body["de"]
        assert "Bewahren Sie den Link vertraulich auf. Er öffnet Ihren Antrag." in body["de"]
        assert "limited time" not in body["en"]
        assert "Keep this link private. It opens your application." in body["en"]
        probe = conn.execute(
            text("SELECT body_i18n FROM mail_template WHERE key = 'mig_probe'")
        ).scalar_one()
        assert probe == _SEED_MAGIC_LINK_BODY
        row = conn.execute(
            text(
                "SELECT id, confirm_ttl_hours, link_ttl_days, updated_by "
                "FROM guest_application_settings"
            )
        ).one()
        assert tuple(row) == (1, 12, None, None)
        kept = conn.execute(text("SELECT expires_at FROM magic_link")).scalar_one()
        assert kept.isoformat().startswith("2026-06-01T10:00")
        conn.execute(
            text(
                "INSERT INTO magic_link (application_id, token_hash, scope, expires_at) "
                "VALUES (:a, '\\x02', 'edit', NULL)"
            ),
            {"a": app_id},
        )
    for bad in (
        "INSERT INTO magic_link (application_id, token_hash, scope, expires_at) "
        "VALUES (:a, '\\x03', 'view', NULL)",
        "UPDATE guest_application_settings SET confirm_ttl_hours = 0",
        "UPDATE guest_application_settings SET confirm_ttl_hours = 721",
        "UPDATE guest_application_settings SET link_ttl_days = 0",
        "INSERT INTO guest_application_settings (id) VALUES (2)",
    ):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text(bad), {"a": app_id})

    command.downgrade(alembic_cfg, "eff772f93d8e")
    with engine.begin() as conn:
        assert conn.execute(
            text("SELECT to_regclass('guest_application_settings')")
        ).scalar_one() is None
        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'magic_link' AND column_name = 'expires_at'"
            )
        ).scalar_one()
        assert nullable == "NO"
        week = conn.execute(
            text(
                "SELECT bool_and(expires_at > now() + interval '6 days') "
                "FROM magic_link WHERE token_hash = '\\x02'"
            )
        ).scalar_one()
        assert week is True
        conn.execute(text("DELETE FROM magic_link"))
        body = conn.execute(
            text("SELECT body_i18n FROM mail_template WHERE key = 'magic_link'")
        ).scalar_one()
        assert body == _SEED_MAGIC_LINK_BODY
        conn.execute(text("DELETE FROM mail_template WHERE key = 'mig_probe'"))
    command.upgrade(alembic_cfg, "head")


def _self_status_check(conn) -> tuple[str, bool] | None:
    """Return the definition and `convalidated` of the self-status check, or None."""
    row = conn.execute(
        text(
            "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
            "WHERE conrelid = 'meeting_attendance'::regclass "
            "AND conname = 'ck_meeting_attendance_self_status'"
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


def test_attendance_self_status_check_not_valid(
    alembic_cfg: Config, engine: Engine, capfd: pytest.CaptureFixture[str]
) -> None:
    """Migration 96421ecdbc54 adds the self-status check as NOT VALID.

    An older (self, absent) row survives the upgrade, and the upgrade logs it. A new
    such row fails. A change of the older row must set an allowed status. The
    downgrade drops the check.
    """
    command.downgrade(alembic_cfg, "d5569d5542c6")
    with engine.begin() as conn:
        assert _self_status_check(conn) is None
        gremium = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', :s) RETURNING id"),
            {"s": f"g-att-{uuid.uuid4()}"},
        ).scalar_one()
        meeting = conn.execute(
            text(
                "INSERT INTO meeting (gremium_id, title, status) "
                "VALUES (:g, 'M', 'closed') RETURNING id"
            ),
            {"g": gremium},
        ).scalar_one()
        people = [
            conn.execute(
                text("INSERT INTO principal (sub) VALUES (:s) RETURNING id"),
                {"s": f"att-{n}-{uuid.uuid4()}"},
            ).scalar_one()
            for n in range(2)
        ]
        legacy = conn.execute(
            text(
                "INSERT INTO meeting_attendance (meeting_id, principal_id, status, source) "
                "VALUES (:m, :p, 'absent', 'self') RETURNING id"
            ),
            {"m": meeting, "p": people[0]},
        ).scalar_one()

    capfd.readouterr()
    command.upgrade(alembic_cfg, "head")
    report = capfd.readouterr().err
    assert "1 older self-reported row(s) with status 'absent'" in report

    with engine.begin() as conn:
        check = _self_status_check(conn)
        assert check is not None
        assert check[1] is False
        assert "source <> 'self'" in check[0]
        status = conn.execute(
            text("SELECT status FROM meeting_attendance WHERE id = :i"), {"i": legacy}
        ).scalar_one()
        assert status == "absent"
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO meeting_attendance (meeting_id, principal_id, status, source) "
                "VALUES (:m, :p, 'absent', 'self')"
            ),
            {"m": meeting, "p": people[1]},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text("UPDATE meeting_attendance SET note = 'x' WHERE id = :i"), {"i": legacy}
        )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO meeting_attendance (meeting_id, principal_id, status, source) "
                "VALUES (:m, :p, 'absent', 'lead')"
            ),
            {"m": meeting, "p": people[1]},
        )
        conn.execute(
            text("UPDATE meeting_attendance SET status = 'excused' WHERE id = :i"),
            {"i": legacy},
        )

    command.downgrade(alembic_cfg, "d5569d5542c6")
    with engine.connect() as conn:
        assert _self_status_check(conn) is None
    command.upgrade(alembic_cfg, "head")


def _has_table(conn, name: str) -> bool:
    return conn.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar_one() is not None


def _attachment_columns(conn) -> dict[str, str]:
    return dict(
        conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'attachment'"
            )
        ).all()
    )


def test_attachment_drafts(alembic_cfg: Config, engine: Engine) -> None:
    """Migration 1ee8a0d3928c.

    The upgrade makes `attachment.application_id` nullable, adds the two draft
    columns, both checks, the two partial indexes and the `attachment_draft_token`
    table. An existing row stays. The downgrade drops the token table, deletes the
    drafts, restores NOT NULL and drops the columns.
    """
    command.downgrade(alembic_cfg, "96421ecdbc54")
    with engine.begin() as conn:
        cols = _attachment_columns(conn)
        assert cols["application_id"] == "NO"
        assert "draft_token_hash" not in cols
        assert not _has_table(conn, "attachment_draft_token")
        type_id = _new_type(conn)
        fv = conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
        ).scalar_one()
        flv = conn.execute(
            text("INSERT INTO flow_version (version) VALUES (1) RETURNING id")
        ).scalar_one()
        app_id = conn.execute(
            text(
                "INSERT INTO application (type_id, form_version_id, flow_version_id) "
                "VALUES (:t, :fv, :flv) RETURNING id"
            ),
            {"t": type_id, "fv": fv, "flv": flv},
        ).scalar_one()
        bound = conn.execute(
            text(
                "INSERT INTO attachment (application_id, filename, mime, size) "
                "VALUES (:a, 'b.pdf', 'application/pdf', 1) RETURNING id"
            ),
            {"a": app_id},
        ).scalar_one()

    command.upgrade(alembic_cfg, "1ee8a0d3928c")
    with engine.begin() as conn:
        cols = _attachment_columns(conn)
        assert cols["application_id"] == "YES"
        assert cols["draft_token_hash"] == "YES"
        assert cols["draft_expires_at"] == "YES"
        indexes = set(
            conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'attachment'")
            ).scalars()
        )
        assert {"ix_attachment_draft_expires_at", "ix_attachment_draft_token_hash"} <= indexes
        assert conn.execute(
            text("SELECT application_id FROM attachment WHERE id = :i"), {"i": bound}
        ).scalar_one() == app_id
        conn.execute(
            text(
                "INSERT INTO attachment (filename, mime, size, draft_token_hash, "
                "draft_expires_at) VALUES ('d.pdf', 'application/pdf', 1, '\\x01', "
                "now() + interval '7 days')"
            )
        )
        assert _has_table(conn, "attachment_draft_token")
        conn.execute(
            text(
                "INSERT INTO attachment_draft_token (token_hash, expires_at) "
                "VALUES ('\\x01', now() + interval '7 days')"
            )
        )
        token_indexes = set(
            conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'attachment_draft_token'"
                )
            ).scalars()
        )
        assert {
            "pk_attachment_draft_token",
            "ix_attachment_draft_token_expires_at",
        } <= token_indexes
    for bad in (
        "INSERT INTO attachment (filename, mime, size) VALUES ('x', 'a/b', 1)",
        "INSERT INTO attachment (application_id, filename, mime, size, "
        "draft_token_hash, draft_expires_at) VALUES (:a, 'x', 'a/b', 1, '\\x01', now())",
        "INSERT INTO attachment (filename, mime, size, draft_token_hash) "
        "VALUES ('x', 'a/b', 1, '\\x01')",
        "INSERT INTO attachment (application_id, filename, mime, size, "
        "draft_expires_at) VALUES (:a, 'x', 'a/b', 1, now())",
    ):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text(bad), {"a": app_id})

    command.downgrade(alembic_cfg, "96421ecdbc54")
    with engine.begin() as conn:
        cols = _attachment_columns(conn)
        assert cols["application_id"] == "NO"
        assert "draft_token_hash" not in cols
        assert "draft_expires_at" not in cols
        assert not _has_table(conn, "attachment_draft_token")
        ids = list(conn.execute(text("SELECT id FROM attachment")).scalars())
        assert ids == [bound]
        conn.execute(text("DELETE FROM attachment"))
    command.upgrade(alembic_cfg, "head")


def test_protocol_keeper_period_backfill(
    alembic_cfg: Config, engine: Engine, capfd: pytest.CaptureFixture[str]
) -> None:
    """Migration 734556b61a72 adds the keeper periods and backfills them.

    A live or closed meeting with a protokollant gets one period. The start is the
    real start, else the planned start in Europe/Berlin, else the creation time. A
    closed meeting ends at `closed_at`, never before the start: a close before the
    planned start keeps the check. A planned meeting and a meeting without a
    protokollant get no period. The downgrade drops the table.
    """
    command.downgrade(alembic_cfg, "1ee8a0d3928c")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT to_regclass('protocol_keeper_period')")).scalar() is None
        gremium = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', :s) RETURNING id"),
            {"s": f"g-keeper-{uuid.uuid4()}"},
        ).scalar_one()
        keeper = conn.execute(
            text("INSERT INTO principal (sub) VALUES (:s) RETURNING id"),
            {"s": f"keeper-{uuid.uuid4()}"},
        ).scalar_one()

        def meeting(status: str, **cols: object) -> uuid.UUID:
            values = {"gremium_id": gremium, "title": "M", "status": status}
            values["protokollant_id"] = cols.pop("protokollant_id", keeper)
            values.update(cols)
            names = list(values)
            placeholders = ", ".join(f":{n}" for n in names)
            return conn.execute(
                text(f"INSERT INTO meeting ({', '.join(names)}) VALUES ({placeholders}) "
                     "RETURNING id"),
                values,
            ).scalar_one()

        live = meeting("live", started_at="2026-06-20T16:05:00+00:00")
        early = meeting(
            "closed", date="2026-06-20", start_time="18:00", closed_at="2026-06-20T15:30:00+00:00"
        )
        closed = meeting(
            "closed",
            date="2026-06-20",
            start_time="18:00",
            closed_at="2026-06-20T19:00:00+00:00",
        )
        undated = meeting("closed")
        planned = meeting("planned", date="2026-06-20", start_time="18:00")
        nobody = meeting("closed", protokollant_id=None)

    capfd.readouterr()
    command.upgrade(alembic_cfg, "734556b61a72")
    assert "4 period(s) backfilled" in capfd.readouterr().err

    with engine.begin() as conn:
        rows = {
            r.meeting_id: r
            for r in conn.execute(
                text(
                    "SELECT meeting_id, principal_id, from_at, to_at, handed_over_by, "
                    "from_agenda_item_id FROM protocol_keeper_period"
                )
            )
        }
        created = conn.execute(
            text("SELECT created_at FROM meeting WHERE id = :m"), {"m": undated}
        ).scalar_one()
    assert set(rows) >= {live, early, closed, undated}
    assert planned not in rows and nobody not in rows
    assert rows[live].from_at.isoformat() == "2026-06-20T16:05:00+00:00"
    assert rows[live].to_at is None
    assert rows[early].from_at.isoformat() == "2026-06-20T16:00:00+00:00"
    assert rows[early].to_at == rows[early].from_at
    assert rows[closed].to_at.isoformat() == "2026-06-20T19:00:00+00:00"
    assert rows[undated].from_at == created == rows[undated].to_at
    assert {r.handed_over_by for r in rows.values()} == {"system:migration"}
    assert {r.principal_id for r in rows.values()} == {keeper}
    assert all(r.from_agenda_item_id is None for r in rows.values())

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO protocol_keeper_period (meeting_id, principal_id, from_at, "
                "handed_over_by) VALUES (:m, :p, now(), 'x')"
            ),
            {"m": live, "p": keeper},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO protocol_keeper_period (meeting_id, principal_id, to_at, "
                "handed_over_by) VALUES (:m, :p, now(), 'x')"
            ),
            {"m": live, "p": keeper},
        )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO protocol_keeper_period (meeting_id, principal_id, "
                "handed_over_by) VALUES (:m, :p, 'x')"
            ),
            {"m": live, "p": keeper},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO protocol_keeper_period (meeting_id, principal_id, "
                "handed_over_by) VALUES (:m, :p, 'x')"
            ),
            {"m": live, "p": keeper},
        )

    command.downgrade(alembic_cfg, "1ee8a0d3928c")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('protocol_keeper_period')")).scalar() is None
    command.upgrade(alembic_cfg, "head")


def test_substitute_groups(alembic_cfg: Config, engine: Engine) -> None:
    """Migration 92f23ad77fc5 adds the faculty substitute groups.

    The upgrade creates both tables with the composite foreign key, the CHECK on
    `kind` and the partial unique index for members. The existing pool entries
    stay. The downgrade drops both tables. A second upgrade runs clean.
    `e12bd65b2a79` drops the tables again, so the checks run at `92f23ad77fc5`.
    """
    command.downgrade(alembic_cfg, "734556b61a72")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT to_regclass('substitute_group')")).scalar() is None
        assert conn.execute(text("SELECT to_regclass('substitute_group_member')")).scalar() is None
        gremium = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', :s) RETURNING id"),
            {"s": f"g-sg-{uuid.uuid4()}"},
        ).scalar_one()
        other = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('H', :s) RETURNING id"),
            {"s": f"g-sg-{uuid.uuid4()}"},
        ).scalar_one()
        person = conn.execute(
            text("INSERT INTO principal (sub) VALUES (:s) RETURNING id"),
            {"s": f"sg-{uuid.uuid4()}"},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO delegation_substitute (gremium_id, substitute_principal_id) "
                "VALUES (:g, :p)"
            ),
            {"g": gremium, "p": person},
        )

    command.upgrade(alembic_cfg, "92f23ad77fc5")
    with engine.begin() as conn:
        names = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid IN "
                    "('substitute_group'::regclass, 'substitute_group_member'::regclass)"
                )
            ).scalars()
        )
        assert {
            "uq_substitute_group_id_gremium",
            "pk_substitute_group_member",
            "fk_substitute_group_member_group",
            "ck_substitute_group_member_kind",
        } <= names
        assert conn.execute(
            text("SELECT to_regclass('uq_substitute_group_member_gremium_member')")
        ).scalar() is not None
        assert conn.execute(
            text("SELECT count(*) FROM delegation_substitute WHERE gremium_id = :g"),
            {"g": gremium},
        ).scalar_one() == 1
        group = conn.execute(
            text(
                "INSERT INTO substitute_group (gremium_id, name_i18n) "
                "VALUES (:g, '{\"de\": \"Info\"}') RETURNING id"
            ),
            {"g": gremium},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO substitute_group_member (group_id, principal_id, gremium_id, kind) "
                "VALUES (:grp, :p, :g, 'member')"
            ),
            {"grp": group, "p": person, "g": gremium},
        )

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO substitute_group_member (group_id, principal_id, gremium_id, kind) "
                "VALUES (:grp, :p, :g, 'substitute')"
            ),
            {"grp": group, "p": person, "g": other},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE substitute_group_member SET kind = 'lead' WHERE group_id = :grp"
            ),
            {"grp": group},
        )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM substitute_group WHERE id = :grp"), {"grp": group})
        assert conn.execute(
            text("SELECT count(*) FROM substitute_group_member WHERE group_id = :grp"),
            {"grp": group},
        ).scalar_one() == 0

    command.downgrade(alembic_cfg, "734556b61a72")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('substitute_group')")).scalar() is None
    command.upgrade(alembic_cfg, "92f23ad77fc5")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('substitute_group')")).scalar() is not None
    command.upgrade(alembic_cfg, "head")


def test_drop_substitute_groups(alembic_cfg: Config, engine: Engine) -> None:
    """Migration e12bd65b2a79 drops the faculty substitute groups.

    The upgrade drops both tables with their rows. The pool entries stay. The
    downgrade is lossy: it creates both tables again, empty, with the composite
    foreign key and the CHECK on `kind`. A second upgrade runs clean.
    """

    def tables(conn: Connection) -> set[str]:
        return {
            name
            for name in ("substitute_group", "substitute_group_member")
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": name}).scalar() is not None
        }

    command.downgrade(alembic_cfg, "4c2570138998")
    with engine.begin() as conn:
        assert tables(conn) == {"substitute_group", "substitute_group_member"}
        gremium = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', :s) RETURNING id"),
            {"s": f"g-dsg-{uuid.uuid4()}"},
        ).scalar_one()
        person = conn.execute(
            text("INSERT INTO principal (sub) VALUES (:s) RETURNING id"),
            {"s": f"dsg-{uuid.uuid4()}"},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO delegation_substitute (gremium_id, substitute_principal_id) "
                "VALUES (:g, :p)"
            ),
            {"g": gremium, "p": person},
        )
        group = conn.execute(
            text(
                "INSERT INTO substitute_group (gremium_id, name_i18n) "
                "VALUES (:g, '{\"de\": \"Info\"}') RETURNING id"
            ),
            {"g": gremium},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO substitute_group_member (group_id, principal_id, gremium_id, kind) "
                "VALUES (:grp, :p, :g, 'member')"
            ),
            {"grp": group, "p": person, "g": gremium},
        )

    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        assert tables(conn) == set()
        assert conn.execute(
            text("SELECT count(*) FROM delegation_substitute WHERE gremium_id = :g"),
            {"g": gremium},
        ).scalar_one() == 1

    command.downgrade(alembic_cfg, "4c2570138998")
    with engine.begin() as conn:
        assert tables(conn) == {"substitute_group", "substitute_group_member"}
        assert conn.execute(text("SELECT count(*) FROM substitute_group")).scalar_one() == 0
        names = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid IN "
                    "('substitute_group'::regclass, 'substitute_group_member'::regclass)"
                )
            ).scalars()
        )
        assert {
            "uq_substitute_group_id_gremium",
            "pk_substitute_group_member",
            "fk_substitute_group_member_group",
            "ck_substitute_group_member_kind",
        } <= names
    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        assert tables(conn) == set()


def test_audit_verification_and_role_key_report(
    alembic_cfg: Config, engine: Engine, capfd: pytest.CaptureFixture[str]
) -> None:
    """Migration 373c9fe9cafb.

    The upgrade adds `audit_verification` with its CHECKs and the index on
    `started_at DESC`. It logs every role key that breaks `^[a-z][a-z0-9_]*$` and
    changes none. The downgrade drops the table.
    """
    command.downgrade(alembic_cfg, "92f23ad77fc5")
    suffix = uuid.uuid4().hex[:6]
    with engine.begin() as conn:
        assert not _has_table(conn, "audit_verification")
        role = conn.execute(
            text("INSERT INTO role (key) VALUES (:k) RETURNING id"), {"k": f"Kasse-{suffix}"}
        ).scalar_one()
        gremium = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES (:n, :s) RETURNING id"),
            {"n": f"Gremium {suffix}", "s": f"g-a10-{suffix}"},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO gremium_role (gremium_id, key) VALUES (:g, :k)"),
            {"g": gremium, "k": f"Schrift Fuehrung {suffix}"},
        )
        conn.execute(
            text("INSERT INTO gremium_role (gremium_id, key) VALUES (:g, :k)"),
            {"g": gremium, "k": f"ok_{suffix}"},
        )

    capfd.readouterr()
    command.upgrade(alembic_cfg, "head")
    err = capfd.readouterr().err
    assert f"role 'Kasse-{suffix}'" in err
    assert f"gremium role 'Schrift Fuehrung {suffix}' in gremium 'Gremium {suffix}'" in err
    assert f"ok_{suffix}" not in err

    with engine.begin() as conn:
        assert _has_table(conn, "audit_verification")
        assert conn.execute(
            text("SELECT key FROM role WHERE id = :i"), {"i": role}
        ).scalar_one() == f"Kasse-{suffix}"
        index = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_audit_verification_started_at'"
            )
        ).scalar_one()
        assert "started_at DESC" in index
        checks = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'audit_verification'::regclass AND contype = 'c'"
                )
            ).scalars()
        )
        assert checks == {
            "ck_audit_verification_trigger",
            "ck_audit_verification_reason",
            "ck_audit_verification_valid_reason",
        }
        conn.execute(
            text(
                "INSERT INTO audit_verification (started_at, valid, checked, trigger) "
                "VALUES (now(), true, 0, 'cron')"
            )
        )

    command.downgrade(alembic_cfg, "92f23ad77fc5")
    with engine.begin() as conn:
        assert not _has_table(conn, "audit_verification")
        conn.execute(text("DELETE FROM gremium_role WHERE gremium_id = :g"), {"g": gremium})
        conn.execute(text("DELETE FROM gremium WHERE id = :g"), {"g": gremium})
        conn.execute(text("DELETE FROM role WHERE id = :i"), {"i": role})
    command.upgrade(alembic_cfg, "head")


def test_public_meeting_guests(alembic_cfg: Config, engine: Engine) -> None:
    """Migration 4c2570138998: the meeting columns, `meeting_guest`, vote counts.

    The downgrade drops them; the upgrade is idempotent on a schema that has them.
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_cfg)
    before = script.get_revision("4c2570138998").down_revision
    assert isinstance(before, str)
    command.downgrade(alembic_cfg, before)
    with engine.begin() as conn:
        assert not _has_table(conn, "meeting_guest")
    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        assert _has_table(conn, "meeting_guest")
        cols = set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'meeting' AND column_name IN "
                    "('public_join','guests_mode','join_code')"
                )
            ).scalars()
        )
        assert cols == {"public_join", "guests_mode", "join_code"}
        checks = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'meeting_guest'::regclass AND contype = 'c'"
                )
            ).scalars()
        )
        assert checks == {"ck_meeting_guest_status"}
        assert conn.execute(
            text("SELECT count(*) FROM pg_indexes WHERE indexname = 'uq_meeting_join_code_open'")
        ).scalar_one() == 1


def test_todo_link_budget_vote_gremium(alembic_cfg: Config, engine: Engine) -> None:
    """Migration 527854b79d68.

    The upgrade adds ``vote_id``, ``gremium_id``, ``invoice_id`` and ``expense_id`` with
    their indexes and widens ``ck_todo_link_one_target``. The downgrade deletes the links
    of the new kinds, drops the columns and keeps the other links.

    A second run of the upgrade on the new schema changes nothing.
    """
    new = ("vote_id", "gremium_id", "invoice_id", "expense_id")

    def columns(conn: Connection) -> set[str]:
        return set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'todo_link'"
                )
            ).scalars()
        )

    with engine.begin() as conn:
        assert set(new) <= columns(conn)
        indexes = set(
            conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'todo_link'")
            ).scalars()
        )
        assert {f"{p}_todo_link_{c}" for c in new for p in ("uq", "ix")} <= indexes
        check = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_todo_link_one_target'"
            )
        ).scalar_one()
        assert "expense_id" in check and "vote_id" in check

    command.downgrade(alembic_cfg, "066ff25554e2")
    with engine.begin() as conn:
        assert not set(new) & columns(conn)
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "066ff25554e2")
    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        assert set(new) <= columns(conn)
        gremium = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('M', :s) RETURNING id"),
            {"s": "mig-" + uuid.uuid4().hex[:8]},
        ).scalar_one()
        who = conn.execute(
            text("INSERT INTO principal (sub) VALUES (:s) RETURNING id"),
            {"s": "mig-" + uuid.uuid4().hex[:8]},
        ).scalar_one()
        board = conn.execute(
            text(
                "INSERT INTO todo_board (name, kind, gremium_id) VALUES ('M', 'gremium', :g) "
                "RETURNING id"
            ),
            {"g": gremium},
        ).scalar_one()
        col = conn.execute(
            text(
                "INSERT INTO todo_column (board_id, name, position, is_done) "
                "VALUES (:b, 'Offen', 0, true) RETURNING id"
            ),
            {"b": board},
        ).scalar_one()
        card = conn.execute(
            text(
                "INSERT INTO todo_card (board_id, column_id, title, rank, created_by) "
                "VALUES (:b, :c, 'K', 'm', :w) RETURNING id"
            ),
            {"b": board, "c": col, "w": who},
        ).scalar_one()
        other = conn.execute(
            text(
                "INSERT INTO todo_card (board_id, column_id, title, rank, created_by) "
                "VALUES (:b, :c, 'L', 'n', :w) RETURNING id"
            ),
            {"b": board, "c": col, "w": who},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO todo_link (card_id, gremium_id, created_by) VALUES (:c, :g, :w)"),
            {"c": card, "g": gremium, "w": who},
        )
        conn.execute(
            text("INSERT INTO todo_link (card_id, todo_id, created_by) VALUES (:c, :t, :w)"),
            {"c": card, "t": other, "w": who},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO todo_link (card_id, gremium_id, todo_id, created_by) "
                "VALUES (:c, :g, :t, :w)"
            ),
            {"c": card, "g": gremium, "t": other, "w": who},
        )

    command.downgrade(alembic_cfg, "066ff25554e2")
    with engine.begin() as conn:
        kinds = conn.execute(text("SELECT todo_id FROM todo_link WHERE card_id = :c"), {"c": card})
        assert list(kinds.scalars()) == [other]
    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM gremium WHERE id = :g"), {"g": gremium})
        conn.execute(text("DELETE FROM principal WHERE id = :w"), {"w": who})


def _vote_status_checks(conn: Connection) -> dict[str, str]:
    """Return the status CHECKs of ``vote`` by name, with their condition."""
    rows = conn.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'vote'::regclass AND contype = 'c' "
            "AND pg_get_constraintdef(oid) LIKE '%status%'"
        )
    )
    return {name: cond for name, cond in rows.tuples()}


def test_fix_vote_status_constraint(alembic_cfg: Config, engine: Engine) -> None:
    """Migration 4fd514277924.

    A database that 0001 built before ``cancelled`` existed keeps the old
    ``ck_vote_vote_status`` beside the ``vote_status`` of 0012, and that old CHECK refuses
    every cancel. The upgrade leaves one CHECK under the convention name that allows
    ``cancelled``. A second run changes nothing.
    """
    command.downgrade(alembic_cfg, "b80a146809d4")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_status"))
        conn.execute(
            text(
                "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_status "
                "CHECK (status IN ('draft','open','closed'))"
            )
        )
        vote = conn.execute(
            text(
                "INSERT INTO vote (eligible_group, config, status) "
                "VALUES ('stupa', '{}'::jsonb, 'open') RETURNING id"
            )
        ).scalar_one()
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE vote SET status = 'cancelled' WHERE id = :v"), {"v": vote})

    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "b80a146809d4")
    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        checks = _vote_status_checks(conn)
        assert list(checks) == ["ck_vote_vote_status"]
        assert "cancelled" in checks["ck_vote_vote_status"]
        conn.execute(text("UPDATE vote SET status = 'cancelled' WHERE id = :v"), {"v": vote})
        conn.execute(text("DELETE FROM vote WHERE id = :v"), {"v": vote})


def test_make_open_votes_secret(alembic_cfg: Config, engine: Engine) -> None:
    """Migration d8a799699d0f.

    An open motion and an open election lose their ``ballot`` rows: each voter gets a
    ``voted_marker`` and each choice a ``secret_ballot``, and ``secret`` becomes true.
    The counts stay the same. A motion without the key ``secret`` is open and converts.
    An election without the key is secret and stays. A poll and a secret motion stay as
    they are. A second run changes nothing.
    """
    command.downgrade(alembic_cfg, "4fd514277924")
    with engine.begin() as conn:

        def _vote(kind: str, config: dict[str, object]) -> uuid.UUID:
            return conn.execute(
                text(
                    "INSERT INTO vote (eligible_group, config, status, kind) "
                    "VALUES ('g', CAST(:c AS jsonb), 'closed', :k) RETURNING id"
                ),
                {"c": json.dumps(config), "k": kind},
            ).scalar_one()

        def _ballot(vote: uuid.UUID, sub: str, choice: str) -> None:
            conn.execute(
                text("INSERT INTO ballot (vote_id, voter_sub, choice) VALUES (:v, :s, :c)"),
                {"v": vote, "s": sub, "c": choice},
            )

        motion = {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
        open_motion = _vote("motion", {**motion, "secret": False})
        keyless_motion = _vote("motion", motion)
        secret_motion = _vote("motion", {**motion, "secret": True})
        election = {"seats": 1, "candidates": [{"id": "c1", "name": "A"}]}
        open_election = _vote("election", {**election, "secret": False})
        keyless_election = _vote("election", election)
        poll = _vote("poll", {"mode": "single", "options": ["a", "b"], "secret": False})
        for sub, choice in (("u1", "yes"), ("u2", "yes"), ("u3", "no")):
            _ballot(open_motion, sub, choice)
        _ballot(keyless_motion, "u1", "abstain")
        _ballot(open_election, "u1", '["c1"]')
        _ballot(poll, "u1", "a")
        conn.execute(
            text("INSERT INTO voted_marker (vote_id, voter_sub) VALUES (:v, 'u1')"),
            {"v": secret_motion},
        )
        conn.execute(
            text("INSERT INTO secret_ballot (vote_id, choice) VALUES (:v, 'no')"),
            {"v": secret_motion},
        )

    command.upgrade(alembic_cfg, "d8a799699d0f")
    command.downgrade(alembic_cfg, "4fd514277924")
    command.upgrade(alembic_cfg, "d8a799699d0f")
    with engine.begin() as conn:

        def _rows(sql: str, vote: uuid.UUID) -> list[str]:
            return sorted(conn.execute(text(sql), {"v": vote}).scalars())

        def _secret(vote: uuid.UUID) -> object:
            return conn.execute(
                text("SELECT config->'secret' FROM vote WHERE id = :v"), {"v": vote}
            ).scalar_one()

        ballots = "SELECT voter_sub FROM ballot WHERE vote_id = :v"
        markers = "SELECT voter_sub FROM voted_marker WHERE vote_id = :v"
        choices = "SELECT choice FROM secret_ballot WHERE vote_id = :v"
        assert _rows(ballots, open_motion) == []
        assert _rows(markers, open_motion) == ["u1", "u2", "u3"]
        assert _rows(choices, open_motion) == ["no", "yes", "yes"]
        assert _secret(open_motion) is True
        assert _rows(markers, keyless_motion) == ["u1"]
        assert _rows(choices, keyless_motion) == ["abstain"]
        assert _secret(keyless_motion) is True
        assert _rows(markers, open_election) == ["u1"]
        assert _rows(choices, open_election) == ['["c1"]']
        assert _secret(open_election) is True
        assert _secret(keyless_election) is None
        assert _rows(markers, secret_motion) == ["u1"]
        assert _rows(choices, secret_motion) == ["no"]
        assert _rows(ballots, poll) == ["u1"]
        assert _rows(markers, poll) == []
        assert _secret(poll) is False
        for vote in (
            open_motion, keyless_motion, secret_motion, open_election, keyless_election, poll
        ):
            conn.execute(text("DELETE FROM vote WHERE id = :v"), {"v": vote})
    command.upgrade(alembic_cfg, "head")


def test_make_open_polls_secret(alembic_cfg: Config, engine: Engine) -> None:
    """Migration 334e15ec6ff5.

    An open poll loses its ``ballot`` rows: each voter gets a ``voted_marker`` and each
    answer a ``secret_ballot``, and ``secret`` becomes true. A poll without the key
    ``secret`` is open and converts. A secret poll and an open motion stay as they are.
    A second run changes nothing.
    """
    command.downgrade(alembic_cfg, "d8a799699d0f")
    with engine.begin() as conn:

        def _vote(kind: str, config: dict[str, object]) -> uuid.UUID:
            return conn.execute(
                text(
                    "INSERT INTO vote (eligible_group, config, status, kind) "
                    "VALUES ('g', CAST(:c AS jsonb), 'closed', :k) RETURNING id"
                ),
                {"c": json.dumps(config), "k": kind},
            ).scalar_one()

        def _ballot(vote: uuid.UUID, sub: str, choice: str) -> None:
            conn.execute(
                text("INSERT INTO ballot (vote_id, voter_sub, choice) VALUES (:v, :s, :c)"),
                {"v": vote, "s": sub, "c": choice},
            )

        poll = {"mode": "single", "options": ["a", "b"]}
        open_poll = _vote("poll", {**poll, "secret": False})
        keyless_poll = _vote("poll", poll)
        secret_poll = _vote("poll", {**poll, "secret": True})
        motion = _vote("motion", {"options": ["yes", "no"], "secret": False})
        for sub, choice in (("u1", '["a"]'), ("u2", '["a"]'), ("u3", '["b"]')):
            _ballot(open_poll, sub, choice)
        _ballot(keyless_poll, "u1", '["b"]')
        _ballot(motion, "u1", "yes")
        conn.execute(
            text("INSERT INTO voted_marker (vote_id, voter_sub) VALUES (:v, 'u1')"),
            {"v": secret_poll},
        )
        conn.execute(
            text("INSERT INTO secret_ballot (vote_id, choice) VALUES (:v, '[\"a\"]')"),
            {"v": secret_poll},
        )

    command.upgrade(alembic_cfg, "334e15ec6ff5")
    command.downgrade(alembic_cfg, "d8a799699d0f")
    command.upgrade(alembic_cfg, "334e15ec6ff5")
    with engine.begin() as conn:

        def _rows(sql: str, vote: uuid.UUID) -> list[str]:
            return sorted(conn.execute(text(sql), {"v": vote}).scalars())

        def _secret(vote: uuid.UUID) -> object:
            return conn.execute(
                text("SELECT config->'secret' FROM vote WHERE id = :v"), {"v": vote}
            ).scalar_one()

        ballots = "SELECT voter_sub FROM ballot WHERE vote_id = :v"
        markers = "SELECT voter_sub FROM voted_marker WHERE vote_id = :v"
        choices = "SELECT choice FROM secret_ballot WHERE vote_id = :v"
        assert _rows(ballots, open_poll) == []
        assert _rows(markers, open_poll) == ["u1", "u2", "u3"]
        assert _rows(choices, open_poll) == ['["a"]', '["a"]', '["b"]']
        assert _secret(open_poll) is True
        assert _rows(markers, keyless_poll) == ["u1"]
        assert _rows(choices, keyless_poll) == ['["b"]']
        assert _secret(keyless_poll) is True
        assert _rows(markers, secret_poll) == ["u1"]
        assert _rows(choices, secret_poll) == ['["a"]']
        assert _rows(ballots, motion) == ["u1"]
        assert _secret(motion) is False
        for vote in (open_poll, keyless_poll, secret_poll, motion):
            conn.execute(text("DELETE FROM vote WHERE id = :v"), {"v": vote})
    command.upgrade(alembic_cfg, "head")


def test_drop_dead_columns(alembic_cfg: Config, engine: Engine) -> None:
    """Migration c71e5a0d9f42.

    The extra protocol recipients move from ``mail_list`` into the gremium. A draft hash
    without a token row gets one. A temporary role assignment, an ended membership and
    a view link go, the plain rows stay. A ``ballot`` row stops the upgrade.
    """
    command.downgrade(alembic_cfg, "b6f901a77cb7")
    with engine.begin() as conn:
        gremium = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('G', 'g-dead') RETURNING id")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO mail_list (gremium_id, name, recipients, active) VALUES "
                "(:g, 'protocol', '{b@x,a@x}', true), (:g, 'off', '{z@x}', false)"
            ),
            {"g": gremium},
        )
        conn.execute(
            text(
                "INSERT INTO attachment (filename, mime, size, draft_token_hash, "
                "draft_expires_at) VALUES ('d', 'a/b', 1, '\\x0f', now() + interval '2 days')"
            )
        )
        principal = conn.execute(
            text("INSERT INTO principal (sub) VALUES ('dead-sub') RETURNING id")
        ).scalar_one()
        role = conn.execute(text("SELECT id FROM role WHERE key = 'member'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO role_assignment (principal_id, role_id, valid_until) VALUES "
                "(:p, :r, now() + interval '1 day'), (:p, :r, NULL)"
            ),
            {"p": principal, "r": role},
        )
        groles = conn.execute(
            text(
                "INSERT INTO gremium_role (gremium_id, key) VALUES (:g, 'member') RETURNING id"
            ),
            {"g": gremium},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO gremium_membership (principal_id, gremium_id, gremium_role_id, "
                "valid_until) VALUES (:p, :g, :r, now() - interval '1 day')"
            ),
            {"p": principal, "g": gremium, "r": groles},
        )

    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        assert conn.execute(
            text("SELECT protocol_recipients FROM gremium WHERE id = :g"), {"g": gremium}
        ).scalar_one() == ["b@x", "a@x"]
        assert conn.execute(text("SELECT to_regclass('mail_list')")).scalar_one() is None
        assert conn.execute(text("SELECT to_regclass('ballot')")).scalar_one() is None
        assert conn.execute(
            text("SELECT count(*) FROM attachment_draft_token WHERE token_hash = '\\x0f'")
        ).scalar_one() == 1
        assert conn.execute(
            text("SELECT count(*) FROM role_assignment WHERE principal_id = :p"),
            {"p": principal},
        ).scalar_one() == 1
        assert conn.execute(
            text("SELECT count(*) FROM gremium_membership WHERE principal_id = :p"),
            {"p": principal},
        ).scalar_one() == 0
        conn.execute(text("DELETE FROM attachment WHERE draft_token_hash = '\\x0f'"))
        conn.execute(text("DELETE FROM attachment_draft_token WHERE token_hash = '\\x0f'"))
        conn.execute(text("DELETE FROM role_assignment WHERE principal_id = :p"), {"p": principal})
        conn.execute(text("DELETE FROM principal WHERE id = :p"), {"p": principal})
        conn.execute(text("DELETE FROM gremium WHERE id = :g"), {"g": gremium})

    command.downgrade(alembic_cfg, "b6f901a77cb7")
    with engine.begin() as conn:
        vote = conn.execute(
            text(
                "INSERT INTO vote (eligible_group, config, status) "
                "VALUES ('g', '{}'::jsonb, 'closed') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text("INSERT INTO ballot (vote_id, voter_sub, choice) VALUES (:v, 's', 'yes')"),
            {"v": vote},
        )
    with pytest.raises(Exception, match="ballot still holds rows"):
        command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM vote WHERE id = :v"), {"v": vote})
    command.upgrade(alembic_cfg, "head")


def _plan_tree(conn: Connection, key: str) -> dict[str, object]:
    """Insert a budget with two Titel, a Kostenstelle and three years, before fea8282a392b."""

    def node(k: str, parent: object, side: str | None, *, plan: bool = False) -> object:
        return conn.execute(
            text(
                "INSERT INTO budget (key, path_key, name, parent_id, side, plan_enabled) "
                "VALUES (:k, :p, :k, :parent, :side, :plan) RETURNING id"
            ),
            {"k": k, "p": f"{key}-{k}", "parent": parent, "side": side, "plan": plan},
        ).scalar_one()

    def year(number: int, *, closed: bool = False) -> object:
        return conn.execute(
            text(
                "INSERT INTO fiscal_year (budget_id, year, start_date, end_date, closed_at) "
                "VALUES (:b, :y, make_date(:y, 1, 1), make_date(:y, 12, 31), "
                "CASE WHEN :closed THEN now() END) RETURNING id"
            ),
            {"b": top, "y": number, "closed": closed},
        ).scalar_one()

    top = node(key, None, None, plan=True)
    inc = node("1", top, "income")
    exp = node("8", top, "expense")
    leaf = node("81", exp, "expense")
    return {
        "top": top, "inc": inc, "exp": exp, "leaf": leaf,
        "made": year(2026), "bare": year(2027), "closed": year(2025, closed=True),
    }


def _plan_version(conn: Connection, fy: object, state: str, steps: str = "[]") -> object:
    plan = conn.execute(
        text("INSERT INTO budget_plan (fiscal_year_id) VALUES (:fy) RETURNING id"), {"fy": fy}
    ).scalar_one()
    return conn.execute(
        text(
            "INSERT INTO budget_plan_version (plan_id, number, state, steps, in_force_at) "
            "VALUES (:p, 0, :s, CAST(:steps AS jsonb), now()) RETURNING id"
        ),
        {"p": plan, "s": state, "steps": steps},
    ).scalar_one()


def test_the_side_moves_from_the_node_to_the_plan_line(
    alembic_cfg: Config, engine: Engine
) -> None:
    """Migration fea8282a392b: the line of a Titel takes the side of its node.

    A line below a Titel holds no side of its own, the node loses the column, and the
    role ``admin`` gets the permission for the state by hand. The downgrade gives the
    node its side again.
    """
    command.downgrade(alembic_cfg, "8d53b821d874")
    with engine.begin() as conn:
        t = _plan_tree(conn, "MIGA")
        version = _plan_version(conn, t["made"], "in_force", '[{"name": "Beschluss"}]')
        for node in ("inc", "exp", "leaf"):
            conn.execute(
                text(
                    "INSERT INTO budget_plan_line (version_id, budget_id, amount, name) "
                    "VALUES (:v, :b, 5, 'alt')"
                ),
                {"v": version, "b": t[node]},
            )

    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        sides = dict(
            conn.execute(
                text("SELECT budget_id, side FROM budget_plan_line WHERE version_id = :v"),
                {"v": version},
            ).all()
        )
        assert sides == {t["inc"]: "income", t["exp"]: "expense", t["leaf"]: None}
        assert conn.execute(
            text("SELECT state FROM budget_plan_version WHERE id = :v"), {"v": version}
        ).scalar_one() == "in_force"
        assert conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'budget' AND column_name = 'side'"
            )
        ).scalar_one() == 0
        assert conn.execute(
            text(
                "SELECT count(*) FROM role_permission rp JOIN role r ON r.id = rp.role_id "
                "WHERE rp.permission = 'budget.plan.set_state' AND r.key = 'admin'"
            )
        ).scalar_one() == 1

    command.downgrade(alembic_cfg, "8d53b821d874")
    with engine.begin() as conn:
        assert dict(
            conn.execute(
                text("SELECT id, side FROM budget WHERE id IN (:a, :b)"),
                {"a": t["inc"], "b": t["exp"]},
            ).all()
        ) == {t["inc"]: "income", t["exp"]: "expense"}
    command.upgrade(alembic_cfg, "head")


def test_a_plan_of_the_switch_goes_back_to_the_draft(
    alembic_cfg: Config, engine: Engine
) -> None:
    """Migration fea8282a392b: a plan that only the switch made is a draft again.

    The allocations stay. An open year without a plan gets a draft from its
    allocations, where a parent holds the sum of its children. A closed year gets none.
    """
    command.downgrade(alembic_cfg, "8d53b821d874")
    with engine.begin() as conn:
        t = _plan_tree(conn, "MIGB")
        made = _plan_version(conn, t["made"], "in_force")
        conn.execute(
            text(
                "INSERT INTO budget_plan_line (version_id, budget_id, amount, name, path_key) "
                "VALUES (:v, :b, 7, 'alt', 'ALT')"
            ),
            {"v": made, "b": t["leaf"]},
        )
        for fy in ("made", "bare", "closed"):
            conn.execute(
                text(
                    "INSERT INTO budget_allocation (budget_id, fiscal_year_id, allocated) "
                    "VALUES (:b, :fy, 7), (:e, :fy, 99)"
                ),
                {"b": t["leaf"], "e": t["exp"], "fy": t[fy]},
            )

    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        assert conn.execute(
            text("SELECT state, in_force_at FROM budget_plan_version WHERE id = :v"), {"v": made}
        ).one() == ("draft", None)
        assert conn.execute(
            text("SELECT name, path_key FROM budget_plan_line WHERE version_id = :v"), {"v": made}
        ).one() == (None, None)
        assert conn.execute(
            text("SELECT count(*) FROM budget_allocation WHERE fiscal_year_id = :fy"),
            {"fy": t["made"]},
        ).scalar_one() == 2
        drafted = conn.execute(
            text(
                "SELECT l.budget_id, l.amount, l.side, v.state, v.number "
                "FROM budget_plan p JOIN budget_plan_version v ON v.plan_id = p.id "
                "JOIN budget_plan_line l ON l.version_id = v.id WHERE p.fiscal_year_id = :fy"
            ),
            {"fy": t["bare"]},
        ).all()
        assert {row[0]: (row[1], row[2], row[3], row[4]) for row in drafted} == {
            t["inc"]: (0, None, "draft", 0),
            t["exp"]: (7, None, "draft", 0),
            t["leaf"]: (7, None, "draft", 0),
        }
        assert conn.execute(
            text("SELECT count(*) FROM budget_plan WHERE fiscal_year_id = :fy"),
            {"fy": t["closed"]},
        ).scalar_one() == 0


def _old_tree(conn: Connection, paths: tuple[str, ...]) -> dict[str, object]:
    """Insert cost centers by their path keys in the form before 9c1f5d3a7e42."""
    ids: dict[str, object] = {}
    for path in paths:
        parent, _, key = path.rpartition("-")
        ids[path] = conn.execute(
            text(
                "INSERT INTO budget (key, path_key, name, parent_id) "
                "VALUES (:k, :p, :k, :parent) RETURNING id"
            ),
            {"k": key, "p": path, "parent": ids.get(parent)},
        ).scalar_one()
    return ids


def test_path_keys_take_the_form_with_one_hyphen(alembic_cfg: Config, engine: Engine) -> None:
    """Migration 9c1f5d3a7e42: the path key has one hyphen, the tree path keeps the tree.

    The line of a decided plan takes the new form too. The way back gives the path key
    with a hyphen per level again. Rule: §F/finance/budget/000878.
    """
    command.downgrade(alembic_cfg, "4b8e2f6c1a93")
    with engine.begin() as conn:
        ids = _old_tree(conn, ("MIGP", "MIGP-801", "MIGP-801-33"))
        fy = conn.execute(
            text(
                "INSERT INTO fiscal_year (budget_id, year, start_date, end_date) "
                "VALUES (:b, 2026, '2026-01-01', '2026-12-31') RETURNING id"
            ),
            {"b": ids["MIGP"]},
        ).scalar_one()
        version = _plan_version(conn, fy, "in_force")
        conn.execute(
            text(
                "INSERT INTO budget_plan_line (version_id, budget_id, amount, name, path_key) "
                "VALUES (:v, :b, 7, 'alt', 'MIGP-801-33')"
            ),
            {"v": version, "b": ids["MIGP-801-33"]},
        )

    command.upgrade(alembic_cfg, "head")
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT tree_path, path_key FROM budget WHERE tree_path LIKE 'MIGP%'")
        ).all()
        assert {(row[0], row[1]) for row in rows} == {
            ("MIGP", "MIGP"), ("MIGP-801", "MIGP-801"), ("MIGP-801-33", "MIGP-80133"),
        }
        assert conn.execute(
            text("SELECT path_key FROM budget_plan_line WHERE version_id = :v"), {"v": version}
        ).scalar_one() == "MIGP-80133"

    command.downgrade(alembic_cfg, "4b8e2f6c1a93")
    with engine.begin() as conn:
        assert set(
            conn.execute(text("SELECT path_key FROM budget WHERE path_key LIKE 'MIGP%'")).scalars()
        ) == {"MIGP", "MIGP-801", "MIGP-801-33"}
    command.upgrade(alembic_cfg, "head")


def test_two_cost_centres_with_one_path_key_stop_the_upgrade(
    alembic_cfg: Config, engine: Engine
) -> None:
    """Migration 9c1f5d3a7e42 names the cost centers that would share a path key.

    It changes no row before it stops. Rule: §F/finance/budget/000878.
    """
    command.downgrade(alembic_cfg, "4b8e2f6c1a93")
    with engine.begin() as conn:
        _old_tree(conn, ("MIGQ", "MIGQ-80", "MIGQ-80-133", "MIGQ-801", "MIGQ-801-33"))
    try:
        with pytest.raises(RuntimeError, match="MIGQ-80133 for MIGQ-80-133, MIGQ-801-33"):
            command.upgrade(alembic_cfg, "head")
        with engine.begin() as conn:
            assert conn.execute(
                text("SELECT count(*) FROM budget WHERE path_key = 'MIGQ-80-133'")
            ).scalar_one() == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM budget WHERE path_key LIKE 'MIGQ-80%-%'"))
            conn.execute(text("DELETE FROM budget WHERE path_key LIKE 'MIGQ%'"))
        command.upgrade(alembic_cfg, "head")
