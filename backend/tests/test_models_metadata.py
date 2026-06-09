"""Metadata-Introspektion des DB-Kerns (T-06) — ohne DB lauffähig.

Prüft, dass `Base.metadata` Tabellen, FK-ON-DELETE, partial-unique-Indizes,
GIN-Index und Checks gemäß data-model §1-3 abbildet (Single Source für Alembic).
"""

from __future__ import annotations

import pytest
from sqlalchemy import ForeignKeyConstraint, Index, Table, UniqueConstraint

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base

EXPECTED_TABLES = {
    "gremium",
    "mail_list",
    "budget_pot",
    "budget_field",
    "application_type",
    "form_version",
    "form_field",
    "flow_version",
    "state",
    "transition",
    "application",
    "applicant",
    "submission_version",
    "status_event",
    "principal",
    "role",
    "role_permission",
    "role_assignment",
    "group_mapping",
}


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _index(table: str, name: str) -> Index:
    idx = next((i for i in _table(table).indexes if i.name == name), None)
    assert idx is not None, f"index {name} fehlt auf {table}"
    return idx


def test_all_core_tables_registered() -> None:
    assert set(Base.metadata.tables) >= EXPECTED_TABLES


def test_uuid_pk_with_gen_random_uuid_default() -> None:
    pk = _table("gremium").c.id
    assert pk.primary_key
    assert "gen_random_uuid()" in str(pk.server_default.arg)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("table", "column", "referred", "ondelete"),
    [
        ("mail_list", "gremium_id", "gremium", "CASCADE"),
        ("budget_field", "budget_pot_id", "budget_pot", "CASCADE"),
        ("form_field", "form_version_id", "form_version", "CASCADE"),
        ("state", "flow_version_id", "flow_version", "CASCADE"),
        ("transition", "flow_version_id", "flow_version", "CASCADE"),
        ("applicant", "application_id", "application", "CASCADE"),
        ("submission_version", "application_id", "application", "CASCADE"),
        ("status_event", "application_id", "application", "CASCADE"),
        ("role_permission", "role_id", "role", "CASCADE"),
        ("role_assignment", "principal_id", "principal", "CASCADE"),
    ],
)
def test_fk_ondelete(table: str, column: str, referred: str, ondelete: str) -> None:
    fk = next(fk for fk in _table(table).c[column].foreign_keys)
    assert fk.column.table.name == referred
    assert fk.ondelete == ondelete


def test_applicant_is_one_to_one() -> None:
    col = _table("applicant").c.application_id
    assert col.unique is True


def test_partial_unique_one_active_form_version() -> None:
    idx = _index("form_version", "uq_form_version_one_active_per_type")
    assert idx.unique
    assert "active" in str(idx.dialect_options["postgresql"]["where"])


def test_partial_unique_one_active_flow_version() -> None:
    idx = _index("flow_version", "uq_flow_version_one_active_per_type")
    assert idx.unique
    assert "active" in str(idx.dialect_options["postgresql"]["where"])


def test_partial_unique_one_initial_state_per_flow() -> None:
    idx = _index("state", "uq_state_one_initial_per_flow")
    assert idx.unique
    assert "is_initial" in str(idx.dialect_options["postgresql"]["where"])


def test_application_data_has_gin_index() -> None:
    idx = _index("application", "ix_application_data")
    assert idx.dialect_options["postgresql"]["using"] == "gin"
    assert idx.dialect_options["postgresql"]["ops"] == {"data": "jsonb_path_ops"}


def test_application_filterable_fk_indexes() -> None:
    names = {i.name for i in _table("application").indexes}
    assert {
        "ix_application_current_state_id",
        "ix_application_gremium_id",
        "ix_application_budget_pot_id",
        "ix_application_type_id",
        "ix_application_created_at",
    } <= names


def test_state_has_color_column() -> None:
    cols = {c.name for c in _table("state").columns}
    assert "color" in cols
    assert "category" not in cols


def test_role_permission_composite_pk() -> None:
    pk = _table("role_permission").primary_key
    assert {c.name for c in pk.columns} == {"role_id", "permission"}


def test_versioned_unique_constraints() -> None:
    for table, cols in [
        ("form_version", {"application_type_id", "version"}),
        ("flow_version", {"application_type_id", "version"}),
        ("submission_version", {"application_id", "version"}),
        ("form_field", {"form_version_id", "key"}),
        ("state", {"flow_version_id", "key"}),
    ]:
        uniques = [
            c
            for c in _table(table).constraints
            if isinstance(c, UniqueConstraint)
        ]
        assert any({col.name for col in u.columns} == cols for u in uniques), (
            f"UNIQUE{tuple(cols)} fehlt auf {table}"
        )


def test_circular_fk_uses_alter() -> None:
    # application_type ↔ form_version/flow_version: zyklischer FK via use_alter.
    circular = [
        c
        for c in _table("application_type").constraints
        if isinstance(c, ForeignKeyConstraint)
        and c.elements[0].column.table.name in {"form_version", "flow_version"}
    ]
    assert {fk.elements[0].column.table.name for fk in circular} == {
        "form_version",
        "flow_version",
    }
    assert all(fk.use_alter for fk in circular)
