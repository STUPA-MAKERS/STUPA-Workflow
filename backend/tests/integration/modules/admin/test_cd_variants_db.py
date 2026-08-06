"""Database invariants of the corporate-design tables on a real Postgres 16.

These are the rules that only the database can hold. The service checks them
too, but the constraint is the last line: no code path, no migration and no
manual SQL can write a broken row.

* `ck_cd_variant_logo_source` — a logo is EITHER vendored OR uploaded.
* `ck_cd_variant_logo_slot` and `ck_cd_variant_base_variant` — closed value sets.
* `fk_gremium_cd_variant_id_cd_variant` is RESTRICT — a variant that a Gremium
  still uses cannot be deleted, so the Gremium is never orphaned.
* The seed reproduces the five variants of before with vendored logos only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def _variant_id(conn, key: str) -> str:  # noqa: ANN001
    return conn.execute(
        text("SELECT id FROM cd_variant WHERE key = :k"), {"k": key}
    ).scalar_one()


def test_seed_holds_the_five_variants_with_vendored_logos(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT key, base_variant FROM cd_variant ORDER BY key")
        ).fetchall()
        logos = conn.execute(
            text(
                "SELECT v.key, l.slot, l.vendored_name, l.object_key "
                'FROM cd_variant_logo l JOIN cd_variant v ON v.id = l.variant_id '
                'ORDER BY v.key, l.slot, l."position"'
            )
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("asta", "protocol"),
        ("echo", "protocol"),
        ("makers", "report"),
        ("report", "report"),
        ("stupa", "protocol"),
    ]
    assert [tuple(r) for r in logos] == [
        ("asta", "footer", "ASTA", None),
        ("asta", "title", "ASTA", None),
        ("echo", "footer", "ECHO", None),
        ("echo", "title", "ECHO", None),
        ("makers", "footer", "MAKERS-RAlign", None),
        ("makers", "title", "MAKERS", None),
        ("report", "title", "INF", None),
        ("stupa", "footer", "STUPA", None),
        ("stupa", "title", "STUPA", None),
    ]


def test_seeded_gremien_point_at_their_variant(engine: Engine) -> None:
    with engine.connect() as conn:
        pairs = conn.execute(
            text(
                "SELECT g.slug, v.key FROM gremium g "
                "JOIN cd_variant v ON v.id = g.cd_variant_id ORDER BY g.slug"
            )
        ).fetchall()
    assert ("stupa", "stupa") in [tuple(p) for p in pairs]
    assert ("asta", "asta") in [tuple(p) for p in pairs]


def test_logo_with_both_sources_is_rejected(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:  # noqa: PT012
        vid = _variant_id(conn, "stupa")
        conn.execute(
            text(
                "INSERT INTO cd_variant_logo (variant_id, slot, vendored_name, object_key) "
                "VALUES (:v, 'title', 'INF', 'cd-logos/a/x.png')"
            ),
            {"v": vid},
        )


def test_logo_without_any_source_is_rejected(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:  # noqa: PT012
        vid = _variant_id(conn, "stupa")
        conn.execute(
            text("INSERT INTO cd_variant_logo (variant_id, slot) VALUES (:v, 'title')"),
            {"v": vid},
        )


def test_logo_with_an_unknown_slot_is_rejected(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:  # noqa: PT012
        vid = _variant_id(conn, "stupa")
        conn.execute(
            text(
                "INSERT INTO cd_variant_logo (variant_id, slot, vendored_name) "
                "VALUES (:v, 'sidebar', 'INF')"
            ),
            {"v": vid},
        )


def test_variant_with_an_unknown_base_variant_is_rejected(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO cd_variant (key, name, base_variant) "
                "VALUES ('x-bad', 'X', 'letter')"
            )
        )


def test_variant_key_is_unique(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text("INSERT INTO cd_variant (key, name) VALUES ('stupa', 'Zweiter StuPa')")
        )


def test_deleting_a_referenced_variant_is_restricted(engine: Engine) -> None:
    """The FK keeps the Gremium intact. The service turns this into a 409."""
    with engine.begin() as conn:
        vid = _variant_id(conn, "echo")
        conn.execute(
            text(
                "INSERT INTO gremium (name, slug, cd_variant_id) "
                "VALUES ('Echo-Test', 'echo-test-cd', :v)"
            ),
            {"v": vid},
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("DELETE FROM cd_variant WHERE key = 'echo'"))
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM gremium WHERE slug = 'echo-test-cd'"))


def test_deleting_a_variant_cascades_to_its_logos(engine: Engine) -> None:
    with engine.begin() as conn:
        vid = conn.execute(
            text(
                "INSERT INTO cd_variant (key, name, base_variant) "
                "VALUES ('temp-cd', 'Temp', 'report') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO cd_variant_logo (variant_id, slot, vendored_name) "
                "VALUES (:v, 'title', 'HSRT')"
            ),
            {"v": vid},
        )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM cd_variant WHERE key = 'temp-cd'"))
        left = conn.execute(
            text("SELECT count(*) FROM cd_variant_logo WHERE variant_id = :v"), {"v": vid}
        ).scalar_one()
    assert left == 0


def test_old_free_text_column_is_gone(engine: Engine) -> None:
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'gremium' AND column_name = 'cd_variant')"
            )
        ).scalar_one()
    assert exists is False


def test_upgrade_from_an_installed_database(engine: Engine) -> None:
    """Drive the branch that the normal chain never reaches.

    On a fresh database `0001_baseline` creates the two tables from the model
    metadata and `0002_seed` writes the five rows, so the raw DDL of the revision
    is a no-op there. An installed database has neither. This test rebuilds that
    state — free-text column back, tables gone — and then runs `_UPGRADE`.
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "ec167d091656_cd_variants.py"
    )
    spec = importlib.util.spec_from_file_location("mig_cd", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with engine.begin() as conn:
        for stmt in mod._DOWNGRADE:  # noqa: SLF001
            conn.execute(text(stmt))
        conn.execute(text("DROP TABLE cd_variant_logo"))
        conn.execute(text("DROP TABLE cd_variant"))
        # An installed database carries the old free text on every Gremium.
        conn.execute(text("UPDATE gremium SET cd_variant = slug"))

    with engine.begin() as conn:
        for stmt in mod._UPGRADE:  # noqa: SLF001
            conn.execute(text(stmt))

    with engine.connect() as conn:
        logos = conn.execute(
            text(
                "SELECT v.key, l.slot, l.vendored_name FROM cd_variant_logo l "
                'JOIN cd_variant v ON v.id = l.variant_id ORDER BY v.key, l.slot, l."position"'
            )
        ).fetchall()
        backfilled = conn.execute(
            text(
                "SELECT g.slug, v.key FROM gremium g "
                "JOIN cd_variant v ON v.id = g.cd_variant_id ORDER BY g.slug"
            )
        ).fetchall()
        old_column = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'gremium' AND column_name = 'cd_variant')"
            )
        ).scalar_one()
    # Both slots of every variant survive. A per-logo guard would have kept the
    # title row only.
    assert [tuple(r) for r in logos] == [
        ("asta", "footer", "ASTA"),
        ("asta", "title", "ASTA"),
        ("echo", "footer", "ECHO"),
        ("echo", "title", "ECHO"),
        ("makers", "footer", "MAKERS-RAlign"),
        ("makers", "title", "MAKERS"),
        ("report", "title", "INF"),
        ("stupa", "footer", "STUPA"),
        ("stupa", "title", "STUPA"),
    ]
    assert ("stupa", "stupa") in [tuple(r) for r in backfilled]
    assert ("asta", "asta") in [tuple(r) for r in backfilled]
    assert old_column is False


def test_admin_role_holds_the_new_permission(engine: Engine) -> None:
    with engine.connect() as conn:
        granted = conn.execute(
            text(
                "SELECT count(*) FROM role_permission rp JOIN role r ON r.id = rp.role_id "
                "WHERE r.key = 'admin' AND rp.permission = 'admin.cd_variants'"
            )
        ).scalar_one()
    assert granted == 1
