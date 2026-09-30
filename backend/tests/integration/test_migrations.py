"""Integration tests for the Alembic migrations and DB constraints on a real Postgres 16.

Acceptance T-06: upgrade and downgrade run clean. The partial unique indexes for the
active form version and the initial state hold. The GIN index exists. The seed creates
the default roles. A deleted application cascades to its applicant rows.
"""

from __future__ import annotations

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

    command.upgrade(alembic_cfg, "head")
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
