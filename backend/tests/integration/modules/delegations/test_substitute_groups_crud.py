"""Z5: the CRUD of the faculty substitute groups through the real API.

* `admin.delegations` or the gremium permission `session.manage` manages the
  groups. `session.manage` of another gremium gives 403, and so does a scoped
  token without the permission in its scope.
* Members, the pool and the managers of the gremium read the groups. Others get
  403.
* A member is in at most one group per gremium (409). A substitute may be in
  more than one group. Above two substitutes the response sets a warning flag.
* The audit log records `delegation_substitute_add` and
  `delegation_substitute_remove`.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditEntry
from app.modules.delegations.models import SubstituteGroupMember
from tests.integration.modules.delegations.conftest import (
    act,
    faculty_group,
    gremium,
    member,
    person,
)

pytestmark = pytest.mark.integration

URL = "/api/delegations/substitute-groups"


async def _actions(maker: async_sessionmaker[AsyncSession]) -> list[tuple[str, str | None]]:
    async with maker() as session:
        rows = await session.execute(
            select(AuditEntry.action, AuditEntry.target_type).order_by(AuditEntry.id)
        )
        return [(a, t) for a, t in rows.all()]


async def test_admin_delegations_manages_a_group(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    gid = await gremium(maker)
    _, mia = await member(maker, gid, "Mia")
    subs = [(await person(maker, f"S{n}"))[1] for n in range(3)]
    act(api, "office", permissions={"admin.delegations"})
    with TestClient(api) as client:
        created = client.post(URL, json={"gremiumId": str(gid), "nameI18n": {"de": "Info"}})
        assert created.status_code == 201, created.text
        group_id = created.json()["id"]
        added = client.post(
            f"{URL}/{group_id}/members", json={"principalId": str(mia), "kind": "member"}
        )
        assert added.status_code == 201, added.text
        for n, sub in enumerate(subs):
            out = client.post(
                f"{URL}/{group_id}/members", json={"principalId": str(sub), "kind": "substitute"}
            )
            assert out.status_code == 201, out.text
            # No hard limit: the flag warns above two substitutes.
            assert out.json()["tooManySubstitutes"] is (n >= 2)
        patched = client.patch(
            f"{URL}/{group_id}", json={"nameI18n": {"de": "Informatik", "en": "CS"}, "position": 2}
        )
        listed = client.get(URL, params={"gremiumId": str(gid)})
        removed = client.delete(f"{URL}/{group_id}/members/{subs[0]}")
        missing = client.delete(f"{URL}/{group_id}/members/{subs[0]}")
        deleted = client.delete(f"{URL}/{group_id}")
        after = client.get(URL, params={"gremiumId": str(gid)})
    assert patched.status_code == 200, patched.text
    assert (patched.json()["nameI18n"], patched.json()["position"]) == (
        {"de": "Informatik", "en": "CS"},
        2,
    )
    group = listed.json()[0]
    kinds = {m["principalId"]: (m["kind"], m["active"]) for m in group["members"]}
    assert kinds[str(mia)] == ("member", True)
    assert kinds[str(subs[0])] == ("substitute", True)
    assert group["members"][0]["displayName"] == "Mia"
    assert removed.status_code == 204
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert deleted.status_code == 204
    assert after.json() == []
    actions = await _actions(maker)
    assert actions.count(("delegation_substitute_add", "substitute_group")) == 1
    assert actions.count(("delegation_substitute_add", "substitute_group_member")) == 4
    assert ("delegation_substitute_remove", "substitute_group_member") in actions
    assert ("delegation_substitute_remove", "substitute_group") in actions


async def test_session_manage_of_the_gremium_only(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    gid = await gremium(maker)
    other = await gremium(maker)
    lead, _ = await member(maker, gid, "Lead", ("session.manage", "vote.cast"))
    act(api, lead)
    with TestClient(api) as client:
        own = client.post(URL, json={"gremiumId": str(gid), "nameI18n": {"de": "Info"}})
        foreign = client.post(URL, json={"gremiumId": str(other), "nameI18n": {"de": "Info"}})
        act(api, lead, scope=frozenset({"meeting.view_all"}))
        scoped = client.post(URL, json={"gremiumId": str(gid), "nameI18n": {"de": "Info"}})
        scoped_delete = client.delete(f"{URL}/{own.json()['id']}")
        act(api, "office", permissions={"admin.delegations"}, scope=frozenset({"read"}))
        admin_scoped = client.post(URL, json={"gremiumId": str(gid), "nameI18n": {"de": "x"}})
    assert own.status_code == 201, own.text
    assert foreign.status_code == 403
    assert foreign.headers["content-type"].startswith("application/problem+json")
    assert scoped.status_code == 403
    assert scoped_delete.status_code == 403
    assert admin_scoped.status_code == 403


async def test_read_access_and_member_writes(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    gid = await gremium(maker)
    plain, pid = await member(maker, gid, "Plain")
    outsider, _ = await person(maker, "Out")
    group_id = await faculty_group(maker, gid, members=(pid,))
    act(api, plain)
    with TestClient(api) as client:
        read = client.get(URL, params={"gremiumId": str(gid)})
        write = client.patch(f"{URL}/{group_id}", json={"position": 1})
        act(api, outsider)
        foreign = client.get(URL, params={"gremiumId": str(gid)})
        unknown = client.get(URL, params={"gremiumId": str(uuid.uuid4())})
    assert read.status_code == 200, read.text
    assert read.json()[0]["nameI18n"] == {"de": "Informatik"}
    assert write.status_code == 403
    assert foreign.status_code == 403
    assert unknown.status_code == 404


async def test_member_in_one_group_substitute_in_many(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    gid = await gremium(maker)
    _, mia = await member(maker, gid, "Mia")
    _, sam = await person(maker, "Sam")
    first = await faculty_group(maker, gid, members=(mia,), substitutes=(sam,))
    second = await faculty_group(maker, gid, name="Technik")
    act(api, "office", permissions={"admin.delegations"})
    with TestClient(api) as client:
        twice = client.post(
            f"{URL}/{second}/members", json={"principalId": str(mia), "kind": "member"}
        )
        again = client.post(
            f"{URL}/{first}/members", json={"principalId": str(sam), "kind": "member"}
        )
        sub_twice = client.post(
            f"{URL}/{second}/members", json={"principalId": str(sam), "kind": "substitute"}
        )
        unknown = client.post(
            f"{URL}/{second}/members", json={"principalId": str(uuid.uuid4()), "kind": "member"}
        )
    assert twice.status_code == 409, twice.text
    assert again.status_code == 409, again.text
    assert sub_twice.status_code == 201, sub_twice.text
    assert unknown.status_code == 404


async def test_the_database_keeps_the_gremium_copy_and_the_member_rule(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    gid = await gremium(maker)
    other = await gremium(maker)
    _, mia = await person(maker, "Mia")
    first = await faculty_group(maker, gid, members=(mia,))
    second = await faculty_group(maker, gid, name="Technik")
    # The composite foreign key refuses a gremium copy that differs from the group.
    async with maker() as session:
        session.add(
            SubstituteGroupMember(
                group_id=first, principal_id=(await person(maker, "X"))[1], gremium_id=other,
                kind="substitute",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
    # The partial unique index puts a member into one group per gremium.
    async with maker() as session:
        session.add(
            SubstituteGroupMember(group_id=second, principal_id=mia, gremium_id=gid, kind="member")
        )
        with pytest.raises(IntegrityError):
            await session.commit()
    # The CHECK refuses an unknown kind.
    async with maker() as session:
        session.add(
            SubstituteGroupMember(group_id=second, principal_id=mia, gremium_id=gid, kind="lead")
        )
        with pytest.raises(IntegrityError):
            await session.commit()
