"""Unit tests for the actor resolution of the timeline, the versions and comments."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.applications.schemas import ActorOut
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    system_actor_key,
)


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("system", "auto"),
        ("system:", "auto"),
        ("system:deadlines", "deadlines"),
        ("system:flow", "flow"),
        ("applicant", None),
        ("e03ad7d7-f039-40d1-b56d-7939b1628e46", None),
        ("systemic", None),
    ],
)
def test_system_actor_key(value: str, key: str | None) -> None:
    assert system_actor_key(value) == key


def test_legacy_string_never_returns_a_raw_sub() -> None:
    assert ActorOut(kind="principal", displayName="Ada").legacy("sub-1") == "Ada"
    assert ActorOut(kind="gremium", displayName="StuPa").legacy("sub-1") == "StuPa"
    assert ActorOut(kind="applicant").legacy("applicant") == "applicant"
    assert ActorOut(kind="system", key="deadlines").legacy("system:deadlines") == (
        "system:deadlines"
    )
    assert ActorOut(kind="deleted").legacy("sub-1") is None


def test_actor_out_serializes_camel_case() -> None:
    out = ActorOut(kind="principal", displayName="Ada").model_dump(by_alias=True)
    assert out == {"kind": "principal", "key": None, "displayName": "Ada"}


def _base(names: dict[str, str]) -> ApplicationsServiceBase:
    svc = ApplicationsServiceBase.__new__(ApplicationsServiceBase)
    svc.session = MagicMock()
    svc._author_names = AsyncMock(return_value=names)  # type: ignore[method-assign]
    svc._applicant_actors = AsyncMock(return_value={"applicant"})  # type: ignore[method-assign]
    svc._gremium_actor = AsyncMock(return_value="StuPa")  # type: ignore[method-assign]
    return svc


async def test_resolve_actors_staff_view() -> None:
    svc = _base({"m-1": "Max"})
    app: Any = MagicMock()
    out = await svc._resolve_actors(
        app,
        ["applicant", "m-1", "system:deadlines", "x-9", None, "m-1"],
        applicant_view=False,
        magic_link_view=False,
    )
    assert out["applicant"].kind == "applicant"
    assert out["m-1"] == ActorOut(kind="principal", displayName="Max")
    assert out["system:deadlines"] == ActorOut(kind="system", key="deadlines")
    assert out["x-9"].kind == "deleted"
    # One batched name lookup, without the applicant and the system keys.
    svc._author_names.assert_awaited_once_with({"m-1", "x-9"})  # type: ignore[attr-defined]
    svc._gremium_actor.assert_not_awaited()  # type: ignore[attr-defined]


async def test_resolve_actors_applicant_view_masks_members() -> None:
    svc = _base({"m-1": "Max"})
    app: Any = MagicMock()
    out = await svc._resolve_actors(
        app,
        ["applicant", "m-1", "system:flow"],
        applicant_view=True,
        magic_link_view=True,
    )
    gremium = ActorOut(kind="gremium", displayName="StuPa")
    assert out == {
        "applicant": ActorOut(kind="applicant"),
        "m-1": gremium,
        "system:flow": gremium,
    }
    # No member name is read for the applicant view.
    svc._author_names.assert_awaited_once_with(set())  # type: ignore[attr-defined]


async def test_resolve_actors_empty() -> None:
    svc = _base({})
    app: Any = MagicMock()
    assert await svc._resolve_actors(app, [None], applicant_view=True, magic_link_view=False) == {}
