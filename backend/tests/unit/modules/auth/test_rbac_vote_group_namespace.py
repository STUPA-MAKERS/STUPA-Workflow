"""An active `vote.cast` Gremium membership adds a namespaced group key.

The membership adds `vote:<gremium_id>` to `Principal.groups`, not the bare UUID as
text. A coincident OIDC group claim can therefore not satisfy the Gremium cast
eligibility.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.auth import rbac
from app.modules.auth.models import Principal as PrincipalRow
from tests._support.auth_fakes import fake_session, result

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


async def test_vote_cast_membership_emits_namespaced_group_key() -> None:
    """Emit a namespaced group key for a vote.cast membership.

    Without assignments, `groups` stays empty, so the code skips the mapping query. An
    empty `role_ids` also skips the permission and role-key queries. Two queries remain:
    the assignments, which are empty, and the membership rows (gremium_id, perms). The
    bare UUID string must not serve as the cast key.
    """
    row = PrincipalRow(sub="u", email=None, display_name=None, oidc_groups=None)
    row.id = "pid"  # type: ignore[assignment]
    gid = "11111111-1111-1111-1111-111111111111"
    db = fake_session(
        result(),
        result((gid, ["vote.cast"])),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert rbac.vote_group_key(gid) in p.groups
    assert gid not in p.groups
