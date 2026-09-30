"""F4 and O7: `protocol.finalize` is an assignable gremium permission.

Before the fix the gremium role catalog did not know the key, so a save stripped it
from every role, and no gremium role could finalize a protocol. The forced roles
`vorstand` and `manager` now carry it by default. `member` does not.
"""

from __future__ import annotations

from uuid import uuid4

from app.modules.admin.gremium_roles import (
    FORCED_ROLE_DEFAULT_PERMS,
    GREMIUM_PERMISSIONS,
    GremiumRoleService,
    _sanitize_perms,
)
from app.modules.admin.models import GremiumRole
from app.modules.admin.schemas import GremiumRoleCreate, GremiumRoleUpdate
from app.shared.permissions import PERMISSION_CATALOGUE
from tests._support.auth_fakes import fake_session, result


def test_catalog_holds_protocol_finalize() -> None:
    assert "protocol.finalize" in GREMIUM_PERMISSIONS
    assert _sanitize_perms(["protocol.finalize", "protocol.write"]) == [
        "protocol.write",
        "protocol.finalize",
    ]


def test_forced_roles_default_to_finalize_for_the_board_only() -> None:
    assert "protocol.finalize" in FORCED_ROLE_DEFAULT_PERMS["vorstand"]
    assert "protocol.finalize" in FORCED_ROLE_DEFAULT_PERMS["manager"]
    assert "protocol.finalize" not in FORCED_ROLE_DEFAULT_PERMS["member"]


def test_global_catalog_drops_the_superseded_keys() -> None:
    """The global keys that a gremium permission replaced are gone (F11 included)."""
    for key in ("meeting.manage", "protocol.finalize", "application.create"):
        assert key not in PERMISSION_CATALOGUE
    # The global read and delete rights of the meeting domain stay.
    assert "meeting.view_all" in PERMISSION_CATALOGUE
    assert "meeting.delete_finalized" in PERMISSION_CATALOGUE


async def test_create_role_keeps_protocol_finalize() -> None:
    db = fake_session(result(), result(), result())  # existing, audit lock, prev hash
    orig_flush = db.flush

    async def _flush() -> None:
        for o in db.added:
            if getattr(o, "id", None) is None:
                o.id = uuid4()
        await orig_flush()

    db.flush = _flush
    out = await GremiumRoleService(db).create_role(
        uuid4(),
        GremiumRoleCreate(key="schrift", permissions=["protocol.finalize", "protocol.write"]),
        "admin",
    )
    assert out.permissions == ["protocol.write", "protocol.finalize"]


async def test_update_role_keeps_protocol_finalize() -> None:
    role = GremiumRole(gremium_id=uuid4(), key="custom", name_i18n={}, permissions=[])
    role.id = uuid4()
    db = fake_session(result(), result(), gets=[role])
    out = await GremiumRoleService(db).update_role(
        role.id, GremiumRoleUpdate(permissions=["protocol.finalize"]), "admin"
    )
    assert out.permissions == ["protocol.finalize"]
    assert role.permissions == ["protocol.finalize"]
