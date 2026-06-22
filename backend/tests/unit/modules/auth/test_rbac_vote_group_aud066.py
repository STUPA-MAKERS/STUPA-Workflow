"""AUD-066: an active ``vote.cast`` gremium membership adds the NAMESPACED
``vote:<gremium_id>`` key (not the bare UUID-as-text) to ``Principal.groups``,
so a coincident OIDC group claim cannot satisfy gremium cast eligibility.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.auth import rbac
from app.modules.auth.models import Principal as PrincipalRow
from tests._support.auth_fakes import fake_session, result

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


async def test_vote_cast_membership_emits_namespaced_group_key() -> None:
    row = PrincipalRow(sub="u", email=None, display_name=None, oidc_groups=None)
    row.id = "pid"  # type: ignore[assignment]
    gid = "11111111-1111-1111-1111-111111111111"
    # Bei leeren Assignments ist ``groups`` leer ⇒ Mapping-Query wird übersprungen;
    # ``role_ids`` leer ⇒ permissions/role_keys-Queries werden übersprungen. Es bleibt:
    # (1) Assignments, (2) Membership-Query.
    db = fake_session(
        result(),  # keine RoleAssignments
        result((gid, ["vote.cast"])),  # Membership: (gremium_id, perms)
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert rbac.vote_group_key(gid) in p.groups
    # Der nackte UUID-String darf NICHT als Cast-Key gesetzt sein (AUD-066).
    assert gid not in p.groups
