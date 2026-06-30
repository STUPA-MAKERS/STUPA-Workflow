"""Domain operations as plain functions over a :class:`~antragsplattform_admin.db.Db`.

SQL uses ``%s`` placeholders (bind params in direct mode, quoted literals in docker mode). Writes
go straight to the DB → NO audit_entry, NO RBAC guards. ``granted_by`` is tagged ``admin-cli`` so
such rows are recognisable.
"""

from __future__ import annotations

from typing import Any

from .db import Db

_GRANTED_BY = "admin-cli"


# --------------------------------------------------------------------------------- users
def list_users(db: Db, search: str | None = None, *, limit: int = 500) -> list[dict[str, Any]]:
    where, params = "", []
    if search and search.strip():
        like = f"%{search.strip()}%"
        where = "WHERE p.email ILIKE %s OR p.display_name ILIKE %s OR p.sub ILIKE %s"
        params = [like, like, like]
    sql = f"""
        SELECT p.id, p.sub, p.email, p.display_name, p.active, p.last_login,
               COALESCE(string_agg(DISTINCT r.key, ', ' ORDER BY r.key), '') AS roles
          FROM principal p
          LEFT JOIN role_assignment ra ON ra.principal_id = p.id
          LEFT JOIN role r ON r.id = ra.role_id
          {where}
         GROUP BY p.id
         ORDER BY p.email NULLS LAST, p.display_name NULLS LAST
         LIMIT %s
    """
    return db.query(sql, (*params, limit))


def set_user_active(db: Db, principal_id: str, active: bool) -> int:
    return db.execute("UPDATE principal SET active = %s WHERE id = %s", (active, principal_id))


def delete_user(db: Db, principal_id: str) -> int:
    # FK ON DELETE CASCADE removes assignments/sessions/etc.
    return db.execute("DELETE FROM principal WHERE id = %s", (principal_id,))


def list_user_roles(db: Db, principal_id: str) -> list[dict[str, Any]]:
    return db.query(
        """
        SELECT ra.id, r.key AS role_key, ra.gremium_id, g.name AS gremium,
               ra.valid_from, ra.valid_until
          FROM role_assignment ra
          JOIN role r ON r.id = ra.role_id
          LEFT JOIN gremium g ON g.id = ra.gremium_id
         WHERE ra.principal_id = %s
         ORDER BY r.key, g.name NULLS FIRST
        """,
        (principal_id,),
    )


def grant_role(db: Db, principal_id: str, role_id: str, gremium_id: str | None) -> int:
    return db.execute(
        """
        INSERT INTO role_assignment (id, principal_id, role_id, gremium_id, granted_by)
        VALUES (gen_random_uuid(), %s, %s, %s, %s)
        """,
        (principal_id, role_id, gremium_id, _GRANTED_BY),
    )


def revoke_assignment(db: Db, assignment_id: str) -> int:
    return db.execute("DELETE FROM role_assignment WHERE id = %s", (assignment_id,))


def list_role_users(db: Db, role_id: str) -> list[dict[str, Any]]:
    """Principals holding the given role (one row per assignment)."""
    return db.query(
        """
        SELECT ra.id AS assignment_id, p.id AS principal_id,
               p.email, p.display_name, p.sub,
               ra.gremium_id, g.name AS gremium
          FROM role_assignment ra
          JOIN principal p ON p.id = ra.principal_id
          LEFT JOIN gremium g ON g.id = ra.gremium_id
         WHERE ra.role_id = %s
         ORDER BY p.email NULLS LAST, p.display_name NULLS LAST
        """,
        (role_id,),
    )


# --------------------------------------------------------------------------------- roles
def list_roles(db: Db) -> list[dict[str, Any]]:
    return db.query(
        """
        SELECT r.id, r.key, r.name_i18n::text AS name_i18n,
               (SELECT count(*) FROM role_permission rp WHERE rp.role_id = r.id) AS perms,
               (SELECT count(*) FROM role_assignment ra WHERE ra.role_id = r.id) AS assignments
          FROM role r
         ORDER BY r.key
        """
    )


def list_roles_simple(db: Db) -> list[dict[str, Any]]:
    return db.query("SELECT id, key FROM role ORDER BY key")


def create_role(db: Db, key: str, name_de: str | None) -> int:
    return db.execute(
        "INSERT INTO role (id, key, name_i18n) VALUES (gen_random_uuid(), %s, jsonb_build_object('de', %s::text))",
        (key, name_de or key),
    )


def rename_role(db: Db, role_id: str, key: str, name_de: str | None) -> int:
    return db.execute(
        "UPDATE role SET key = %s, name_i18n = jsonb_build_object('de', %s::text) WHERE id = %s",
        (key, name_de or key, role_id),
    )


def delete_role(db: Db, role_id: str) -> int:
    return db.execute("DELETE FROM role WHERE id = %s", (role_id,))


def list_role_permissions(db: Db, role_id: str) -> list[str]:
    rows = db.query(
        "SELECT permission FROM role_permission WHERE role_id = %s ORDER BY permission",
        (role_id,),
    )
    return [str(r["permission"]) for r in rows]


def set_role_permissions(db: Db, role_id: str, permissions: list[str]) -> None:
    """Replace the role's permission set (delete-all + bulk insert). Two statements → run in both
    backends sequentially (autocommit; acceptable for an admin tool)."""
    db.execute("DELETE FROM role_permission WHERE role_id = %s", (role_id,))
    perms = sorted(set(permissions))
    if not perms:
        return
    values = ",".join(["(%s, %s)"] * len(perms))
    params: list[Any] = []
    for perm in perms:
        params += [role_id, perm]
    db.execute(
        f"INSERT INTO role_permission (role_id, permission) VALUES {values} "
        "ON CONFLICT DO NOTHING",
        tuple(params),
    )


# ----------------------------------------------------------------------- OIDC group mappings
def list_mappings(db: Db) -> list[dict[str, Any]]:
    return db.query(
        """
        SELECT gm.id, gm.oidc_group, r.key AS role_key, gm.role_id,
               gm.gremium_id, g.name AS gremium
          FROM group_mapping gm
          JOIN role r ON r.id = gm.role_id
          LEFT JOIN gremium g ON g.id = gm.gremium_id
         ORDER BY gm.oidc_group, r.key
        """
    )


def create_mapping(db: Db, oidc_group: str, role_id: str, gremium_id: str | None) -> int:
    return db.execute(
        "INSERT INTO group_mapping (id, oidc_group, role_id, gremium_id) "
        "VALUES (gen_random_uuid(), %s, %s, %s)",
        (oidc_group, role_id, gremium_id),
    )


def update_mapping(
    db: Db, mapping_id: str, oidc_group: str, role_id: str, gremium_id: str | None
) -> int:
    return db.execute(
        "UPDATE group_mapping SET oidc_group = %s, role_id = %s, gremium_id = %s WHERE id = %s",
        (oidc_group, role_id, gremium_id, mapping_id),
    )


def delete_mapping(db: Db, mapping_id: str) -> int:
    return db.execute("DELETE FROM group_mapping WHERE id = %s", (mapping_id,))


# --------------------------------------------------------------------------------- gremien
def list_gremien(db: Db) -> list[dict[str, Any]]:
    return db.query("SELECT id, name FROM gremium ORDER BY name")


# --------------------------------------------------------------------------------- audit log
def list_audit(
    db: Db, *, before_id: int | None = None, action: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if before_id is not None:
        clauses.append("id < %s")
        params.append(before_id)
    if action and action.strip():
        clauses.append("action ILIKE %s")
        params.append(f"%{action.strip()}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT id, at, actor, action, target_type, target_id, data::text AS data
          FROM audit_entry
          {where}
         ORDER BY id DESC
         LIMIT %s
    """
    return db.query(sql, (*params, limit))
