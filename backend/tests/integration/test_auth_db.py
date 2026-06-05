"""Integration: T-10-Tabellen gegen echtes Postgres 16 (security.md §1/§2).

Prüft Schema-Verhalten der Migration: magic_link (scope-CHECK, bytea-Hash,
FK-CASCADE) und auth_session (sid UNIQUE, principal-FK-CASCADE).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError


def _new_application(conn) -> str:  # noqa: ANN001
    type_id = conn.execute(
        text("INSERT INTO application_type (key) VALUES (:k) RETURNING id"),
        {"k": "t-" + str(conn.execute(text("SELECT gen_random_uuid()")).scalar())},
    ).scalar_one()
    fv = conn.execute(
        text("INSERT INTO form_version (application_type_id, version) VALUES (:t,1) RETURNING id"),
        {"t": type_id},
    ).scalar_one()
    flv = conn.execute(
        text("INSERT INTO flow_version (application_type_id, version) VALUES (:t,1) RETURNING id"),
        {"t": type_id},
    ).scalar_one()
    return conn.execute(
        text(
            "INSERT INTO application (type_id, form_version_id, flow_version_id) "
            "VALUES (:t,:fv,:flv) RETURNING id"
        ),
        {"t": type_id, "fv": fv, "flv": flv},
    ).scalar_one()


def test_magic_link_scope_check_rejects_bad_scope(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:  # noqa: PT012
        app_id = _new_application(conn)
        conn.execute(
            text(
                "INSERT INTO magic_link (application_id, token_hash, scope, expires_at) "
                "VALUES (:a, :h, 'bogus', now())"
            ),
            {"a": app_id, "h": b"\x00" * 32},
        )


def test_magic_link_cascade_on_application_delete(engine: Engine) -> None:
    with engine.begin() as conn:
        app_id = _new_application(conn)
        conn.execute(
            text(
                "INSERT INTO magic_link (application_id, token_hash, scope, expires_at) "
                "VALUES (:a, :h, 'edit', now())"
            ),
            {"a": app_id, "h": b"\x01" * 32},
        )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM application WHERE id=:a"), {"a": app_id})
    with engine.connect() as conn:
        left = conn.execute(text("SELECT count(*) FROM magic_link")).scalar_one()
    assert left == 0


def test_auth_session_sid_unique_and_cascade(engine: Engine) -> None:
    with engine.begin() as conn:
        pid = conn.execute(
            text("INSERT INTO principal (sub) VALUES (:s) RETURNING id"),
            {"s": "sub-" + str(conn.execute(text("SELECT gen_random_uuid()")).scalar())},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO auth_session (sid, principal_id, expires_at) "
                "VALUES ('sid-unique-1', :p, now())"
            ),
            {"p": pid},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:  # noqa: PT012
        conn.execute(
            text(
                "INSERT INTO auth_session (sid, principal_id, expires_at) "
                "VALUES ('sid-unique-1', :p, now())"
            ),
            {"p": pid},
        )
    # FK-CASCADE: Principal löschen entfernt Session.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM principal WHERE id=:p"), {"p": pid})
    with engine.connect() as conn:
        left = conn.execute(
            text("SELECT count(*) FROM auth_session WHERE sid='sid-unique-1'")
        ).scalar_one()
    assert left == 0
