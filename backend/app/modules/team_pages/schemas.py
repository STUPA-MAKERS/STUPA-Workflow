"""The bodies of the team routes (F/collaboration/teams/003074)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

TeamRole = Literal["member", "manager"]


class TeamOut(FrozenCamelModel, frozen=True):
    """A team in the list, with the rights of the caller.

    ``gremiumId`` marks an inherent team, ``parentId`` a sub-team. ``isMember`` and
    ``canManage`` are the own rights of the caller (``canManage`` includes the admin).
    ``boardId`` is the own board of the team. ``memberCount`` is the number of active members
    of a free team; an inherent team leaves it null, because its Gremium carries the count.
    """

    id: UUID
    name: str
    gremium_id: UUID | None = Field(default=None, serialization_alias="gremiumId")
    parent_id: UUID | None = Field(default=None, serialization_alias="parentId")
    parent_name: str | None = Field(default=None, serialization_alias="parentName")
    board_id: UUID | None = Field(default=None, serialization_alias="boardId")
    member_count: int | None = Field(default=None, serialization_alias="memberCount")
    is_member: bool = Field(default=False, serialization_alias="isMember")
    can_manage: bool = Field(default=False, serialization_alias="canManage")


class TeamMemberOut(FrozenCamelModel, frozen=True):
    """A member of a team. An inherent team names no role and allows no change."""

    principal_id: UUID = Field(serialization_alias="principalId")
    display_name: str = Field(serialization_alias="displayName")
    role: TeamRole | None = None


class TeamDetailOut(FrozenCamelModel, frozen=True):
    """A team with its members and its sub-teams.

    ``members`` is empty for a caller who is neither a member nor a manager.
    """

    team: TeamOut
    members: tuple[TeamMemberOut, ...] = ()
    sub_teams: tuple[TeamOut, ...] = Field(default=(), serialization_alias="subTeams")


class TeamCreate(FrozenStrictCamelModel, frozen=True):
    """A new free team: its name and its parent (null for a team at the top)."""

    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = Field(default=None, alias="parentId")


class TeamPatch(FrozenStrictCamelModel, frozen=True):
    """A new name of a free team, or a new parent (``parentId`` null moves it to the top)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: UUID | None = Field(default=None, alias="parentId")


class TeamMemberIn(FrozenStrictCamelModel, frozen=True):
    """The role of a member of a free team."""

    role: TeamRole = "member"
