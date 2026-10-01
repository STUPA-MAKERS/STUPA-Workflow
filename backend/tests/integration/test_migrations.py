"""Integration tests for the Alembic migrations and DB constraints on a real Postgres 16.

Acceptance T-06: upgrade and downgrade run clean. The partial unique indexes for the
active form version and the initial state hold. The GIN index exists. The seed creates
the default roles. A deleted application cascades to its applicant rows.
"""

from __future__ import annotations

import json
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError


def _new_type(conn) -> str:  # noqa: ANN001
    return conn.execute(
        text("INSERT INTO application_type (key) VALUES (:k) RETURNING id"),
        {"k": "t-" + str(conn.execute(text("SELECT gen_random_uuid()")).scalar())},
    ).scalar_one()


def test_upgrade_and_downgrade_clean(alembic_cfg: Config, engine: Engine) -> None:
    # The fixture already upgraded to head. This test runs the round trip head, base, head.
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
    with pytest.raises(IntegrityError), engine.begin() as conn:  # noqa: PT012
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
    with pytest.raises(IntegrityError), engine.begin() as conn:  # noqa: PT012
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
        # Rebuild the legacy schema: drop the new invariants and add the old column back.
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
        for stmt in mod._UPGRADE:  # noqa: SLF001
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
    """Migration 3a0b9672fcba drops the superseded global meeting keys (O7, F11).

    The upgrade gives `protocol.finalize` to the forced gremium roles `vorstand` and
    `manager` only, and deletes the three global keys from every role. The downgrade
    restores the seed grants and takes `protocol.finalize` off every gremium role.
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

    def _gremium_perms(conn) -> dict[str, list[str]]:  # noqa: ANN001
        rows = conn.execute(
            text("SELECT key, permissions FROM gremium_role WHERE gremium_id = :g"),
            {"g": gid},
        ).all()
        return {r[0]: list(r[1]) for r in rows}

    def _dropped(conn) -> list[tuple[str, str]]:  # noqa: ANN001
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

    # Stop at 3a0b9672fcba: b0c8fd389e10 also gives the key to `schrift`.
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

    # The downgrade restores the seed grants of the seeded roles.
    command.downgrade(alembic_cfg, "14ed7a68a641")
    with engine.connect() as conn:
        perms = _gremium_perms(conn)
        restored = _dropped(conn)
    assert all("protocol.finalize" not in p for p in perms.values())
    assert ("manager", "meeting.manage") in restored
    assert ("admin", "protocol.finalize") in restored
    assert ("protocol", "meeting.manage") in restored
    # Lossy by design: a custom role does not get its key back.
    assert all(key != "sitzungsdienst" for key, _ in restored)

    # The upgrade runs again cleanly and adds the key exactly once.
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

    def _gremium_perms(conn) -> dict[str, list[str]]:  # noqa: ANN001
        rows = conn.execute(
            text("SELECT key, permissions FROM gremium_role WHERE gremium_id = :g"),
            {"g": gid},
        ).all()
        return {r[0]: list(r[1]) for r in rows}

    def _dropped(conn) -> list[tuple[str, str]]:  # noqa: ANN001
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

    # `env.py` runs `fileConfig`, which resets the handlers of the alembic loggers. The
    # console handler of `alembic.ini` writes the report to stderr, so read it there.
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
    assert perms["sitzungsleitung"] == ["session.manage", "protocol.write", "protocol.finalize"]
    assert perms["schrift"] == ["protocol.write"]
    assert perms["vorsitz"] == ["session.manage", "protocol.finalize"]
    assert kept == ["application.read"]
    # Report, delete nothing.
    assert {free_vote, foreign_vote, good_vote} <= votes
    assert str(free_vote) in report
    assert str(foreign_vote) in report
    assert str(good_vote) not in report
    assert "'wahlleitung' loses the permission(s): vote.manage" in report

    # The downgrade restores the seed grants of the seeded roles only.
    command.downgrade(alembic_cfg, "3a0b9672fcba")
    with engine.connect() as conn:
        restored = _dropped(conn)
    assert ("admin", "vote.cast") in restored
    assert ("admin", "vote.manage") in restored
    assert ("manager", "vote.manage") in restored
    assert ("member", "vote.cast") in restored
    assert all(key != "wahlleitung" for key, _ in restored)
    # The downgrade keeps the `protocol.finalize` grants (see the migration docstring).
    with engine.connect() as conn:
        perms = _gremium_perms(conn)
    assert "protocol.finalize" in perms["sitzungsleitung"]

    # The upgrade runs again cleanly and adds the key exactly once.
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

    # The downgrade is a no-op, and a second upgrade finds nothing to delete.
    command.downgrade(alembic_cfg, "b0c8fd389e10")
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM notification_preference WHERE principal_id = :p"),
            {"p": pid},
        ).scalar_one() == 1
    command.upgrade(alembic_cfg, "head")
    # `principal` and `mail_template` are not in the truncate list of the fixture.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM principal WHERE id = :p"), {"p": pid})
        conn.execute(text("DELETE FROM mail_template WHERE key = 'meeting_created'"))


def test_vote_closed_at_backfill_and_allow_change_strip(
    alembic_cfg: Config, engine: Engine, capfd: pytest.CaptureFixture[str]
) -> None:
    """Migration 863a6833fea5 adds `vote.closed_at` (Z9, O10, O11, O18).

    The upgrade backfills `closed_at` from the `status_change` audit entry of the result
    branch, at or after the open time, and keeps NULL where the audit log has no such
    entry. It removes `allowChange` from every vote config and reports the meeting
    votes with the result `tie`. The downgrade drops the column.
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
                text(f"INSERT INTO vote ({names}) VALUES ({values}) RETURNING id"),  # noqa: S608
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
        # Two status changes of the branch: one BEFORE the open (an older vote of the
        # same application) and the real one. The backfill takes the first one at or
        # after the open time.
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


def _agenda_fk_rule(conn) -> str:  # noqa: ANN001
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
    """Migration eff772f93d8e adds `meeting.started_at` and keeps agenda votes (Z7, F21).

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
    command.upgrade(alembic_cfg, "head")
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
    """Migration d5569d5542c6 (Z1, O3).

    The upgrade creates the settings row (12 hours, no link expiry), makes
    `magic_link.expires_at` nullable and allows NULL only for an edit link. The
    existing links keep their expiry. The downgrade gives a link without an expiry
    seven days, restores NOT NULL and drops the table.
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
        # The seed text of the magic-link mail. Another template with the same text
        # must stay as it is.
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

    command.upgrade(alembic_cfg, "head")
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


def _self_status_check(conn) -> tuple[str, bool] | None:  # noqa: ANN001
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
    """Migration 96421ecdbc54 adds the self-status check as NOT VALID (Z2).

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
        assert check[1] is False  # NOT VALID
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
        # A lead row keeps "absent", and the older row moves to an allowed status.
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
