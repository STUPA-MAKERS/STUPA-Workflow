"""AUD-066: gremium cast eligibility must not be satisfiable by a raw OIDC group
claim that merely equals a gremium UUID string.

``resolve_principal`` puts both raw OIDC group claims and gremium-membership keys
into ``Principal.groups``. The cast gate for a gremium-scoped vote now depends on
the NAMESPACED ``vote:<gremium_id>`` key (``rbac.vote_group_key``) that only a real
``vote.cast`` Gremium-membership sets — so a hostile/misconfigured IdP emitting a
UUID-shaped group name can no longer slip into the cast roster.
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
    member = Principal(sub="m", permissions={"vote.cast"}, groups={vote_group_key(gid)})
    assert VotingService._eligible_group_member(member, str(gid)) is True


def test_bare_uuid_oidc_claim_does_not_satisfy_eligibility() -> None:
    """AUD-066 core: a raw OIDC group claim equal to the gremium UUID is rejected."""
    gid = uuid.uuid4()
    attacker = Principal(sub="a", permissions={"vote.cast"}, groups={str(gid)})
    assert VotingService._eligible_group_member(attacker, str(gid)) is False


def test_non_uuid_eligible_group_uses_oidc_group_path() -> None:
    """Free (non-UUID) group keys keep the direct OIDC-group membership check."""
    p = Principal(sub="u", permissions={"vote.cast"}, groups={"stupa"})
    assert VotingService._eligible_group_member(p, "stupa") is True
    assert VotingService._eligible_group_member(p, "asta") is False
