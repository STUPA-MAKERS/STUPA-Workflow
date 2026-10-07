"""Unit tests of the public protocols page (no database).

They cover the snapshot model, the semester helpers, the reads of
`PublicProtocolService` over a fake session, the public router (noindex header,
query validation, PDF download), and the rate limits of the public routes. The
integration suite runs the same paths against Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from datetime import date as _date
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import create_app
from app.modules.files.storage import StorageError
from app.modules.protocol import public as pub
from app.modules.protocol.public import (
    PublicDecision,
    PublicFilter,
    PublicProtocolService,
    PublicSnapshot,
    PublicTop,
    apply_public_snapshot,
    meeting_day,
    semester_of,
    semester_range,
)
from app.modules.protocol.public_router import get_public_protocol_service
from app.settings import get_settings
from app.shared import antiabuse
from app.shared.errors import NotFoundError, RateLimitedError, ServiceUnavailableError
from app.shared.ratelimit import InMemoryRateLimiter

PID = uuid.uuid4()
GID = uuid.uuid4()


def _snapshot() -> PublicSnapshot:
    return PublicSnapshot(
        tops=[
            PublicTop(
                number=1,
                title="Sommerfest",
                markdown="Text",
                decisions=[
                    PublicDecision(question="Q?", counts={"ja": 3}, result="passed"),
                    PublicDecision(question=None, result=None),
                ],
            ),
            PublicTop(number=2, title="Geheim", nonPublic=True, markdown="Geheim"),
        ],
    )


def _rows(
    *, slug: str = "fs-inf", key: str | None = "pdf/protocol/x-public.pdf", day: Any = None
) -> tuple[Any, Any, Any]:
    protocol = SimpleNamespace(
        id=PID,
        sent_at=datetime(2026, 10, 2, tzinfo=UTC),
        public_content=_snapshot().model_dump(mode="json", by_alias=True),
        public_pdf_storage_key=key,
        public_pdf_size=1234,
    )
    meeting = SimpleNamespace(
        title="6. Sitzung",
        date=_date(2026, 9, 29) if day is None else day,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    gremium = SimpleNamespace(id=GID, name="Fachschaft Informatik", slug=slug)
    return protocol, meeting, gremium


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Session:
    """Answer `execute` from an ordered queue and record the statements."""

    def __init__(self, results: list[list[Any]], scalars: list[Any] | None = None) -> None:
        self.results = results
        self.scalar_values = scalars or []
        self.statements: list[str] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(str(stmt))
        return _Result(self.results.pop(0) if self.results else [])

    async def scalar(self, stmt: Any) -> Any:
        self.statements.append(str(stmt))
        return self.scalar_values.pop(0) if self.scalar_values else None


class _Storage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def get(self, key: str) -> bytes:
        if self.fail:
            raise StorageError("down")
        return b"%PDF-public"


# ---------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("day", "key"),
    [
        (_date(2026, 10, 1), "ws-2026"),
        (_date(2027, 3, 31), "ws-2026"),
        (_date(2026, 4, 1), "ss-2026"),
        (_date(2026, 9, 30), "ss-2026"),
    ],
)
def test_semester_of(day: _date, key: str) -> None:
    assert semester_of(day) == key
    first, last = semester_range(key)
    assert first <= day <= last


def test_meeting_day_falls_back_to_creation() -> None:
    meeting = SimpleNamespace(date=None, created_at=datetime(2026, 5, 4, 10, tzinfo=UTC))
    assert meeting_day(meeting) == _date(2026, 5, 4)  # type: ignore[arg-type]


def test_snapshot_search_text_and_results() -> None:
    snap = _snapshot()
    assert snap.tops[0].results == ["passed"]
    text = snap.search_text()
    assert "Sommerfest" in text and "Text" in text and "Q?" in text
    assert "Geheim" not in text
    free = PublicSnapshot(markdown="Freitext")
    assert free.search_text() == "Freitext"


def test_apply_snapshot_sets_size_only_with_pdf() -> None:
    row = SimpleNamespace(public_content=None, public_search_text=None, public_pdf_size=None)
    apply_public_snapshot(row, _snapshot(), None)  # type: ignore[arg-type]
    assert row.public_content["tops"][1]["nonPublic"] is True
    assert row.public_pdf_size is None
    apply_public_snapshot(row, _snapshot(), b"1234")  # type: ignore[arg-type]
    assert row.public_pdf_size == 4


def test_decision_from_vote() -> None:
    view = SimpleNamespace(
        question="Q?",
        tally=SimpleNamespace(counts={"yes": 2, "no": 1}),
        result="rejected",
        majority_rule="two_thirds",
        secret=True,
    )
    dec = PublicDecision.from_vote(view)
    assert dec.counts == {"yes": 2, "no": 1}
    assert dec.result == "rejected"
    assert dec.majority_rule == "two_thirds"
    assert dec.secret is True
    bare = PublicDecision.from_vote(SimpleNamespace())
    assert bare.counts == {} and bare.result is None and bare.majority_rule == "simple"


# ---------------------------------------------------------------- service


async def test_list_protocols_maps_rows_and_filters() -> None:
    session = _Session([[_rows()]], scalars=[1])
    svc = PublicProtocolService(session, storage=_Storage())  # type: ignore[arg-type]
    page = await svc.list_protocols(
        PublicFilter(gremium_ids=(GID,), semester="ss-2026", year=2026, q="50%_x"),
        limit=10,
        offset=0,
    )
    assert page.total == 1
    item = page.items[0]
    assert item.semester == "ss-2026"
    assert item.has_pdf is True
    assert [t.title for t in item.tops] == ["Sommerfest", None]
    assert item.tops[0].results == ["passed"]
    sql = " ".join(session.statements)
    assert "protocols_public IS true" in sql
    assert "public_withheld IS false" in sql
    assert "LIKE" in sql.upper()


async def test_list_protocols_without_storage_has_no_pdf() -> None:
    session = _Session([[_rows()]], scalars=[None])
    svc = PublicProtocolService(session)  # type: ignore[arg-type]
    page = await svc.list_protocols(PublicFilter(), limit=10, offset=0)
    assert page.total == 0
    assert page.items[0].has_pdf is False


async def test_list_gremien_and_semesters() -> None:
    session = _Session(
        [
            [(GID, "AStA", "asta", 3)],
            [(_date(2026, 10, 5),), (_date(2026, 11, 5),), (_date(2026, 5, 1),)],
        ]
    )
    svc = PublicProtocolService(session)  # type: ignore[arg-type]
    gremien = await svc.list_gremien()
    assert gremien[0].protocol_count == 3
    semesters = await svc.list_semesters(PublicFilter(semester="ws-2026"))
    assert [(s.key, s.count) for s in semesters] == [("ws-2026", 2), ("ss-2026", 1)]


async def test_get_protocol_hides_non_public_content() -> None:
    session = _Session([[_rows()]])
    svc = PublicProtocolService(session, storage=_Storage())  # type: ignore[arg-type]
    detail = await svc.get_protocol(PID)
    assert detail.tops[0].markdown == "Text"
    assert detail.tops[1].title is None
    assert detail.tops[1].markdown is None
    assert detail.tops[1].decisions == []
    assert detail.attendance.present == 0


async def test_get_protocol_missing_is_404() -> None:
    svc = PublicProtocolService(_Session([[]]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.get_protocol(PID)


async def test_get_pdf_paths() -> None:
    svc = PublicProtocolService(_Session([[_rows(slug='a"b/c')]]), storage=_Storage())  # type: ignore[arg-type]
    data, name = await svc.get_pdf(PID)
    assert data == b"%PDF-public"
    assert name == "Protokoll_abc_2026-09-29_oeffentlich.pdf"

    svc = PublicProtocolService(_Session([[_rows(slug="!!")]]), storage=_Storage())  # type: ignore[arg-type]
    assert (await svc.get_pdf(PID))[1].startswith("Protokoll_gremium_")

    svc = PublicProtocolService(_Session([[_rows(key=None)]]), storage=_Storage())  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.get_pdf(PID)

    svc = PublicProtocolService(_Session([[_rows()]]))  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await svc.get_pdf(PID)

    svc = PublicProtocolService(_Session([[_rows()]]), storage=_Storage(fail=True))  # type: ignore[arg-type]
    with pytest.raises(ServiceUnavailableError):
        await svc.get_pdf(PID)


# ---------------------------------------------------------------- router


class _FakeService:
    def __init__(self) -> None:
        self.filters: list[PublicFilter] = []

    async def list_gremien(self) -> list[pub.PublicGremiumOut]:
        return [pub.PublicGremiumOut(id=GID, name="AStA", slug="asta", protocolCount=1)]

    async def list_protocols(
        self, flt: PublicFilter, *, limit: int, offset: int
    ) -> pub.PublicProtocolPage:
        self.filters.append(flt)
        return pub.PublicProtocolPage(items=[], total=0, limit=limit, offset=offset)

    async def list_semesters(self, flt: PublicFilter) -> list[pub.PublicSemesterOut]:
        self.filters.append(flt)
        return [pub.PublicSemesterOut(key="ws-2026", count=1)]

    async def get_protocol(self, protocol_id: uuid.UUID) -> pub.PublicProtocolDetail:
        raise NotFoundError("protocol not found")

    async def get_pdf(self, protocol_id: uuid.UUID) -> tuple[bytes, str]:
        return b"%PDF", "Protokoll_asta_2026-10-05_oeffentlich.pdf"


@pytest.fixture
def client() -> Iterator[tuple[TestClient, _FakeService]]:
    app: FastAPI = create_app(get_settings())
    fake = _FakeService()
    app.dependency_overrides[get_public_protocol_service] = lambda: fake
    app.dependency_overrides[antiabuse.get_rate_limiter] = InMemoryRateLimiter
    yield TestClient(app), fake
    app.dependency_overrides.clear()


def test_router_lists_with_filters_and_noindex(
    client: tuple[TestClient, _FakeService],
) -> None:
    http, fake = client
    res = http.get(
        "/api/public/protocols",
        params={"gremium": [str(GID)], "semester": "ws-2026", "year": 2026, "q": "  Haus  "},
    )
    assert res.status_code == 200
    assert res.headers["X-Robots-Tag"] == "noindex"
    assert fake.filters[-1] == PublicFilter(
        gremium_ids=(GID,), semester="ws-2026", year=2026, q="Haus"
    )
    http.get("/api/public/protocols", params={"q": "   "})
    assert fake.filters[-1].q is None
    assert http.get("/api/public/protocols", params={"semester": "x"}).status_code == 422
    nul = http.get("/api/public/protocols?q=%00")
    assert nul.status_code == 422
    assert nul.headers["X-Robots-Tag"] == "noindex"
    assert http.get("/api/public/protocols/semesters?q=a%00b").status_code == 422
    assert http.get("/api/public/protocols", params={"limit": 51}).status_code == 422
    sem = http.get("/api/public/protocols/semesters", params={"q": "a"})
    assert sem.json() == [{"key": "ws-2026", "count": 1}]
    gremien = http.get("/api/public/gremien")
    assert gremien.json()[0]["protocolCount"] == 1
    assert gremien.headers["X-Robots-Tag"] == "noindex"


def test_router_detail_404_and_pdf(client: tuple[TestClient, _FakeService]) -> None:
    http, _ = client
    missing = http.get(f"/api/public/protocols/{PID}")
    assert missing.status_code == 404
    assert missing.headers["X-Robots-Tag"] == "noindex"
    pdf = http.get(f"/api/public/protocols/{PID}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-disposition"] == (
        'attachment; filename="Protokoll_asta_2026-10-05_oeffentlich.pdf"'
    )
    # Other API routes carry no noindex header from this rule.
    assert "X-Robots-Tag" not in http.get("/api/health").headers


def test_router_builds_the_real_service() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    svc = get_public_protocol_service(object(), request)  # type: ignore[arg-type]
    assert isinstance(svc, PublicProtocolService)
    assert svc.storage is None


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/public/protocols",
            "headers": [],
            "client": ("10.0.0.9", 1),
        }
    )


async def test_public_protocol_rate_limits() -> None:
    settings = get_settings().model_copy(
        update={"rl_public_protocols_ip_per_hour": 1, "rl_public_protocol_pdf_ip_per_hour": 1}
    )
    limiter = InMemoryRateLimiter()
    await antiabuse.rate_limit_public_protocols(_request(), settings, limiter)
    with pytest.raises(RateLimitedError):
        await antiabuse.rate_limit_public_protocols(_request(), settings, limiter)
    await antiabuse.rate_limit_public_protocol_pdf(_request(), settings, limiter)
    with pytest.raises(RateLimitedError):
        await antiabuse.rate_limit_public_protocol_pdf(_request(), settings, limiter)


def test_unhandled_error_on_a_public_route_keeps_noindex() -> None:
    app: FastAPI = create_app(get_settings())

    class _Broken(_FakeService):
        async def list_gremien(self) -> list[pub.PublicGremiumOut]:
            raise RuntimeError("db down")

    app.dependency_overrides[get_public_protocol_service] = _Broken
    app.dependency_overrides[antiabuse.get_rate_limiter] = InMemoryRateLimiter
    http = TestClient(app, raise_server_exceptions=False)
    res = http.get("/api/public/gremien")
    assert res.status_code == 500
    assert res.headers["X-Robots-Tag"] == "noindex"
    assert res.headers["content-type"].startswith("application/problem+json")
