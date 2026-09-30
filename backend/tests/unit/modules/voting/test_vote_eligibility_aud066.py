"""AUD-066: a raw OIDC group claim must not satisfy the gremium cast eligibility.

A hostile or misconfigured IdP can emit a group name that equals a gremium UUID string.
`resolve_principal` puts both raw OIDC group claims and gremium membership keys into
`Principal.groups`. The cast gate of a gremium-scoped vote now needs the namespaced
`vote:<gremium_id>` key from `rbac.vote_group_key`. Only a real `vote.cast` Gremium
membership sets that key, so such a claim can no longer reach the cast roster.
"""

from __future__ import annotations

import uuid

from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.voting.service import VotingService


def test_vote_group_key_is_namespaced() -> None:
    gid = uuid.uuid4()
    assert vote_group_key(gid) == f"vote:{gid}"
    # The namespaced key can never equal the bare UUID-as-text an OIDC claim could carry.
    assert vote_group_key(gid) != str(gid)


def test_uuid_eligible_group_requires_namespaced_membership_key() -> None:
    """A gremium-UUID vote is castable only with the namespaced membership key."""
    gid = uuid.uuid4()
    member = Principal(sub="m", groups={vote_group_key(gid)})
    assert VotingService._may_cast(member, str(gid)) is True


def test_bare_uuid_oidc_claim_does_not_satisfy_eligibility() -> None:
    """AUD-066 core: the gate rejects a raw OIDC group claim equal to the gremium UUID."""
    gid = uuid.uuid4()
    attacker = Principal(sub="a", groups={str(gid)})
    assert VotingService._may_cast(attacker, str(gid)) is False


def test_non_uuid_eligible_group_admits_nobody() -> None:
    """A free (non-UUID) group key is an old row: no group or permission casts in it."""
    p = Principal(sub="u", roles=["admin"], permissions={"vote.cast"}, groups={"stupa"})
    assert VotingService._may_cast(p, "stupa") is False
