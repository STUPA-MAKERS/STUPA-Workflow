"""Unit tests for the global search.

The point of these is the authorization claim in the module docstring: a source must not
answer for a caller who could not reach that record through the module's own list. A fake
session cannot prove the reuse, so each source is exercised through its permission gate
and the delegation is asserted where it is cheap to observe.
"""

from __future__ import annotations

import uuid
from typing import Any, get_args

import pytest

from app.modules.auth.principal import Principal
from app.modules.search.schemas import SearchHit, SearchKind
from app.modules.search.service import (
    HIT_URL,
    MIN_QUERY_LENGTH,
    PER_KIND,
    SearchService,
)


def _svc(**sources: Any) -> SearchService:
    """A service with every source stubbed out, so a test opts IN to what it exercises."""
    svc = SearchService(session=None)  # type: ignore[arg-type]
    for name in (
        "_applications",
        "_meetings",
        "_invoices",
        "_expenses",
        "_budgets",
        "_gremien",
        "_principals",
    ):

        async def _empty(*_a: object, **_kw: object) -> list[SearchHit]:
            return []

        setattr(svc, name, sources.get(name, _empty))
    return svc


def _hit(i: int = 0) -> SearchHit:
    return SearchHit(kind="application", id=str(uuid.uuid4()), title=f"hit {i}", url="/x")


ANY = Principal(sub="u")


async def test_a_query_shorter_than_the_floor_asks_no_source() -> None:
    """The palette calls this on every keystroke. The first one is not a mistake."""
    calls: list[str] = []

    async def _spy(*_a: object, **_kw: object) -> list[SearchHit]:
        calls.append("called")
        return []

    svc = _svc(_applications=_spy)
    out = await svc.search("a" * (MIN_QUERY_LENGTH - 1), ANY)
    assert out.hits == []
    assert calls == []


async def test_whitespace_does_not_count_towards_the_floor() -> None:
    svc = _svc()
    assert (await svc.search("   x   ", ANY)).hits == []


async def test_a_source_over_the_cap_is_trimmed_and_reported() -> None:
    async def _many(*_a: object, **_kw: object) -> list[SearchHit]:
        return [_hit(i) for i in range(PER_KIND + 3)]

    out = await _svc(_applications=_many).search("query", ANY)
    assert len(out.hits) == PER_KIND
    assert out.truncated is True


async def test_a_source_at_the_cap_is_not_reported_as_truncated() -> None:
    async def _exact(*_a: object, **_kw: object) -> list[SearchHit]:
        return [_hit(i) for i in range(PER_KIND)]

    out = await _svc(_applications=_exact).search("query", ANY)
    assert len(out.hits) == PER_KIND
    assert out.truncated is False


async def test_one_broken_source_does_not_empty_the_palette() -> None:
    """A palette that shows the other kinds beats one that shows a stack trace."""

    async def _boom(*_a: object, **_kw: object) -> list[SearchHit]:
        raise RuntimeError("source is down")

    async def _ok(*_a: object, **_kw: object) -> list[SearchHit]:
        return [_hit()]

    out = await _svc(_applications=_boom, _meetings=_ok).search("query", ANY)
    assert [h.title for h in out.hits] == ["hit 0"]
    assert out.failed == ["application"]


async def test_the_language_reaches_every_source() -> None:
    """A hit is one flat line, so a translated label must be resolved server-side."""
    seen: list[str] = []

    async def _spy(_q: str, _p: Principal, lang: str) -> list[SearchHit]:
        seen.append(lang)
        return []

    await _svc(_applications=_spy, _meetings=_spy).search("query", ANY, lang="en")
    assert seen == ["en", "en"]


@pytest.mark.parametrize(
    ("source", "perms"),
    [
        ("_invoices", ("budget.view", "budget.structure", "budget.book")),
        ("_expenses", ("budget.view", "budget.structure", "budget.book")),
        ("_principals", ("admin.users", "admin.gremien")),
    ],
)
async def test_a_gated_source_answers_nothing_without_its_permission(
    source: str, perms: tuple[str, ...]
) -> None:
    """The gate is the module's own. Without it the source must not even query."""
    svc = SearchService(session=None)  # type: ignore[arg-type]
    assert await getattr(svc, source)("query", Principal(sub="u"), "de") == []


@pytest.mark.parametrize("perm", ["admin.users", "admin.gremien"])
async def test_a_gremium_hit_needs_somewhere_to_go(perm: str) -> None:
    """A Gremium row links to the members page, which only an administrator may open.

    A caller who cannot open it would get a label with nowhere to go, so the source
    answers nothing for them rather than showing dead rows.
    """
    svc = SearchService(session=None)  # type: ignore[arg-type]
    assert await svc._gremien("query", Principal(sub="u"), "de") == []


def test_every_kind_has_a_url_that_names_the_record() -> None:
    """A hit must land on the thing it names, not on the list it lives in.

    Invoices, bookings and people used to link to `/invoices`, `/expenses` and
    `/admin/users`: picking one of five people out of the palette opened the whole user
    list, and the reader searched a second time. One table rather than a URL built at
    each source, so a kind added later cannot quietly repeat that.
    """
    kinds = set(get_args(SearchKind))
    assert set(HIT_URL) == kinds

    for kind, template in HIT_URL.items():
        assert "{id}" in template, kind
        # Filled in, the URL has to differ from the plain page: a template that ignores
        # its id would still pass the check above if the id sat in a comment.
        assert template.format(id="X") != template.format(id="Y"), kind


async def test_applications_source_includes_archived_and_marks_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A search must reach an archived application, and say that it is one.

    The list hides archived rows by default, which is right for a working list and wrong
    here: archiving a record does not make it stop existing, and someone searching by
    name is looking for that one record.
    """
    from types import SimpleNamespace

    from app.modules.applications.service import ApplicationsService

    seen: dict[str, object] = {}
    live_id, filed_id = uuid.uuid4(), uuid.uuid4()

    async def _fake_list(_self: object, **kw: object) -> object:
        seen.update(kw)
        return SimpleNamespace(
            items=[
                SimpleNamespace(id=live_id, title="Laufender Antrag", state=None, archived_at=None),
                SimpleNamespace(
                    id=filed_id, title="Alter Antrag", state=None, archived_at="2026-01-01"
                ),
            ]
        )

    monkeypatch.setattr(ApplicationsService, "list_applications", _fake_list)

    svc = SearchService(session=None)  # type: ignore[arg-type]
    principal = Principal(sub="s", email=None, display_name=None, roles=[], permissions=set())
    hits = await svc._applications("antrag", principal, "de")

    assert seen["archived"] is None, "None means both; False would hide the archived one"
    assert [h.archived for h in hits] == [False, True]
    assert [h.id for h in hits] == [str(live_id), str(filed_id)]
