"""Integration: Alembic-Migrationen + DB-Constraints gegen echtes Postgres 16.

Akzeptanz T-06: upgrade/downgrade sauber; partial-unique (active/initial) greifen;
GIN-Index vorhanden; Seed legt Default-Rollen an; FK-CASCADE (applicant).
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
    # head ist bereits erreicht (fixture). Voller Round-Trip: head → base → head.
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
        type_id = _new_type(conn)
        fv = conn.execute(
            text(
                "INSERT INTO flow_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
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
        type_id = _new_type(conn)
        fv = conn.execute(
            text(
                "INSERT INTO flow_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
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
                "INSERT INTO flow_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
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
                "INSERT INTO flow_version (application_type_id, version) "
                "VALUES (:t, 1) RETURNING id"
            ),
            {"t": type_id},
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
