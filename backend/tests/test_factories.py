"""Smoke-Tests der Test-Infra (Factories, freezegun) — testing.md §5."""

from __future__ import annotations

import datetime as dt

from freezegun import freeze_time

from app.shared.paging import DEFAULT_LIMIT, MAX_LIMIT, PageParams
from tests.factories import PageParamsFactory, seed_core


def test_pageparams_factory_respects_constraints() -> None:
    params = PageParamsFactory.build()
    assert isinstance(params, PageParams)
    assert 1 <= params.limit <= MAX_LIMIT
    assert params.offset >= 0


def test_factory_overrides() -> None:
    params = PageParamsFactory.build(limit=DEFAULT_LIMIT, offset=0)
    assert params.limit == DEFAULT_LIMIT
    assert params.offset == 0


def test_seed_core_stub_passthrough() -> None:
    assert seed_core(gremium="x", rollen=["admin"]) == {"gremium": "x", "rollen": ["admin"]}


@freeze_time("2026-06-05T12:00:00Z")
def test_freezegun_available() -> None:
    # Frist-/Token-/Vote-Fenster-Tests verlassen sich auf eingefrorene Zeit (§5).
    assert dt.datetime.now(tz=dt.UTC).date().isoformat() == "2026-06-05"
