"""Integration tests of the public protocols page (real Postgres, real app wiring).

The tests finalize protocols through `ProtocolService` with fake storage and typst,
then read them through the public API without login. They check the fail-closed
visibility (non-public gremium, draft, held back: 404), that a non-public TOP keeps
its number only, that no name of any person reaches a public answer, the
`X-Robots-Tag: noindex` header, the search, the semester filter, the PDF stream,
the backfill after the gremium switch, and the audit entries of both switches.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from datetime import date as _date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.flow.models import FlowVersion
from app.modules.forms.models import FormVersion
from app.modules.livevote.models import (
    Meeting,
    MeetingAgendaItem,
    MeetingAttendance,
    MeetingGuest,
)
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import ProtocolService
from app.modules.voting.models import Vote
from tests.integration.modules.livevote.conftest import CONFIG

pytestmark = pytest.mark.integration

PRESENT = "Anna Anwesend"
EXCUSED = "Erik Entschuldigt"
ABSENT = "Bernd Abwesend"
KEEPER = "Petra Protokoll"
GUEST = "Gisela Gast"
SECRET_TITLE = "Personalangelegenheit Müller"
SECRET_BODY = "Vertrauliche Abwägung zur Stelle."
PUBLIC_BODY = "Der Haushalt **Sommerfest** wurde vorgestellt."
QUESTION = "Soll das Sommerfest gefördert werden?"
NAMES = (PRESENT, EXCUSED, ABSENT, KEEPER, GUEST)


class _Storage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]


class _Typst:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        self.calls.append(markdown)
        return f"%PDF-{len(self.calls)}::{markdown}".encode()


async def _seed(
    maker: async_sessionmaker[AsyncSession],
    *,
    public: bool = True,
    title: str = "34. Sitzung",
    day: _date = _date(2026, 9, 29),
    non_public_item: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Write a closed meeting with a draft protocol. Return gremium, meeting, protocol."""
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        gremium = Gremium(name=f"Gremium {tag}", slug=f"g-{tag}", protocols_public=public)
        session.add(gremium)
        await session.flush()
        people = {
            name: PrincipalRow(sub=f"{name[:4]}-{tag}", display_name=name)
            for name in (PRESENT, EXCUSED, ABSENT, KEEPER)
        }
        session.add_all(people.values())
        await session.flush()
        meeting = Meeting(
            gremium_id=gremium.id,
            title=title,
            date=day,
            status="closed",
            protokollant_id=people[KEEPER].id,
        )
        session.add(meeting)
        await session.flush()
        for name, status in ((PRESENT, "present"), (EXCUSED, "excused"), (ABSENT, "absent")):
            session.add(
                MeetingAttendance(
                    meeting_id=meeting.id, principal_id=people[name].id, status=status
                )
            )
        now = datetime.now(UTC)
        session.add(
            MeetingGuest(
                meeting_id=meeting.id,
                seq=1,
                display_name=GUEST,
                status="admitted",
                requested_at=now,
                admitted_at=now,
            )
        )
        public_item = MeetingAgendaItem(
            meeting_id=meeting.id, title="Sommerfest", body=PUBLIC_BODY, position=0
        )
        session.add(public_item)
        if non_public_item:
            session.add(
                MeetingAgendaItem(
                    meeting_id=meeting.id,
                    title=SECRET_TITLE,
                    body=SECRET_BODY,
                    position=1,
                    non_public=True,
                )
            )
        await session.flush()
        session.add(
            Vote(
                application_id=None,
                meeting_id=meeting.id,
                agenda_item_id=public_item.id,
                eligible_group=str(gremium.id),
                question=QUESTION,
                config=CONFIG,
                status="closed",
                result="passed",
            )
        )
        protocol = Protocol(meeting_id=meeting.id, gremium_id=gremium.id, status="draft")
        session.add(protocol)
        await session.commit()
        return gremium.id, meeting.id, protocol.id


async def _finalize(
    maker: async_sessionmaker[AsyncSession],
    protocol_id: uuid.UUID,
    storage: _Storage,
    *,
    withheld: bool = False,
) -> None:
    async with maker() as session:
        svc = ProtocolService(session, storage=storage, typst=_Typst())  # type: ignore[arg-type]
        await svc.start_finalize(protocol_id, actor="admin-p5a", public_withheld=withheld)
        await svc.finalize(protocol_id, now=datetime.now(UTC))


def _enter(client: TestClient, api: FastAPI, storage: _Storage | None) -> None:
    api.state.object_storage = storage
    api.state.arq_pool = None


@pytest.fixture(autouse=True)
def _fake_typst(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the API render calls (finalize, inline backfill) to the fake typst."""
    from app.modules.protocol import router as protocol_router

    monkeypatch.setattr(protocol_router, "build_typst_client", lambda _settings: _Typst())


def _assert_no_names(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for name in NAMES:
        assert name not in text
    assert SECRET_TITLE not in text
    assert SECRET_BODY not in text


async def test_public_list_and_detail_hide_names_and_non_public_tops(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The public list and detail hide the names and the non-public TOPs.

    The public PDF is served, never the internal one with the names.
    """
    storage = _Storage()
    gremium_id, _, protocol_id = await _seed(maker)
    await _finalize(maker, protocol_id, storage)

    with TestClient(api) as client:
        _enter(client, api, storage)
        listing = client.get("/api/public/protocols", params={"gremium": str(gremium_id)})
        assert listing.status_code == 200
        assert listing.headers["X-Robots-Tag"] == "noindex"
        body = listing.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["id"] == str(protocol_id)
        assert item["title"] == "34. Sitzung"
        assert item["date"] == "2026-09-29"
        assert item["semester"] == "ss-2026"
        assert item["hasPdf"] is True
        assert item["pdfSize"] > 0
        assert item["tops"] == [
            {"number": 1, "title": "Sommerfest", "nonPublic": False, "results": ["passed"]},
            {"number": 2, "title": None, "nonPublic": True, "results": []},
        ]
        _assert_no_names(body)

        detail = client.get(f"/api/public/protocols/{protocol_id}")
        assert detail.status_code == 200
        assert detail.headers["X-Robots-Tag"] == "noindex"
        data = detail.json()
        assert data["attendance"] == {"present": 1, "excused": 1, "absent": 1, "guests": 1}
        assert data["tops"][0]["markdown"] == PUBLIC_BODY
        assert data["tops"][0]["decisions"][0]["question"] == QUESTION
        assert data["tops"][0]["decisions"][0]["result"] == "passed"
        assert data["tops"][1] == {
            "number": 2,
            "title": None,
            "nonPublic": True,
            "results": [],
            "markdown": None,
            "decisions": [],
        }
        assert data["markdown"] is None
        _assert_no_names(data)

        pdf = client.get(f"/api/public/protocols/{protocol_id}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["X-Robots-Tag"] == "noindex"
        assert "attachment" in pdf.headers["content-disposition"]
        assert "_2026-09-29_oeffentlich.pdf" in pdf.headers["content-disposition"]
        text = pdf.content.decode()
        for name in NAMES:
            assert name not in text
        assert SECRET_BODY not in text

        gremien = client.get("/api/public/gremien").json()
        ours = [g for g in gremien if g["id"] == str(gremium_id)]
        assert ours and ours[0]["protocolCount"] == 1
        assert set(ours[0]) == {"id", "name", "slug", "protocolCount"}


async def test_application_items_carry_the_application_title(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    """An application item shows the application title, as on the meeting page.

    Without a title it shows the neutral heading.
    """
    storage = _Storage()
    gremium_id, meeting_id, protocol_id = await _seed(maker, non_public_item=False)
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        app_type = ApplicationType(
            gremium_id=gremium_id, key=f"t-{tag}", name_i18n={}, has_budget=False
        )
        session.add(app_type)
        await session.flush()
        form_version = FormVersion(application_type_id=app_type.id, version=1)
        flow_version = FlowVersion(version=1)
        session.add_all([form_version, flow_version])
        await session.flush()
        for position, data in ((1, {"title": "  Lastenrad  "}), (2, {})):
            application = Application(
                type_id=app_type.id,
                form_version_id=form_version.id,
                flow_version_id=flow_version.id,
                data=data,
            )
            session.add(application)
            await session.flush()
            session.add(
                MeetingAgendaItem(
                    meeting_id=meeting_id, application_id=application.id, position=position
                )
            )
        await session.commit()
    await _finalize(maker, protocol_id, storage)

    with TestClient(api) as client:
        _enter(client, api, storage)
        data = client.get(f"/api/public/protocols/{protocol_id}").json()
        assert [top["title"] for top in data["tops"]] == [
            "Sommerfest",
            "Lastenrad",
            "Tagesordnungspunkt",
        ]
        pdf = client.get(f"/api/public/protocols/{protocol_id}/pdf").content.decode()
        assert "# Lastenrad" in pdf


async def test_hidden_protocols_answer_404_with_noindex(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    """A hidden protocol answers 404 with noindex.

    Hidden are the protocols of a gremium that does not publish, a draft of a public
    gremium, and a held-back protocol of a public gremium.
    """
    storage = _Storage()
    private_gid, _, private_pid = await _seed(maker, public=False)
    await _finalize(maker, private_pid, storage)
    _, _, draft_pid = await _seed(maker)
    withheld_gid, _, withheld_pid = await _seed(maker)
    await _finalize(maker, withheld_pid, storage, withheld=True)

    with TestClient(api) as client:
        _enter(client, api, storage)
        for pid in (private_pid, draft_pid, withheld_pid, uuid.uuid4()):
            for path in (f"/api/public/protocols/{pid}", f"/api/public/protocols/{pid}/pdf"):
                res = client.get(path)
                assert res.status_code == 404, path
                assert res.headers["X-Robots-Tag"] == "noindex"
                assert res.headers["content-type"].startswith("application/problem+json")
        listed = client.get(
            "/api/public/protocols",
            params={"gremium": [str(private_gid), str(withheld_gid)]},
        ).json()
        assert listed["total"] == 0
        ids = {g["id"] for g in client.get("/api/public/gremien").json()}
        assert str(private_gid) not in ids
        assert str(withheld_gid) not in ids


async def test_search_semester_and_paging(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The search covers the meeting title and the public TOP text, also with LIKE wildcards.

    A non-public TOP is never searched. The list is newest first, with paging, and the
    semester and year filters apply.
    """
    storage = _Storage()
    gid_a, _, pid_a = await _seed(maker, title="Sitzung Herbst", day=_date(2026, 10, 5))
    gid_b, _, pid_b = await _seed(maker, title="Sitzung Frühjahr", day=_date(2026, 2, 3))
    for pid in (pid_a, pid_b):
        await _finalize(maker, pid, storage)
    scope = {"gremium": [str(gid_a), str(gid_b)]}

    with TestClient(api) as client:
        _enter(client, api, storage)
        hits = client.get("/api/public/protocols", params={**scope, "q": "herbst"}).json()
        assert [i["id"] for i in hits["items"]] == [str(pid_a)]
        hits = client.get("/api/public/protocols", params={**scope, "q": "Sommerfest"}).json()
        assert hits["total"] == 2
        assert client.get("/api/public/protocols", params={**scope, "q": "%"}).json()["total"] == 0
        assert (
            client.get("/api/public/protocols", params={**scope, "q": "Vertrauliche"}).json()[
                "total"
            ]
            == 0
        )
        page = client.get("/api/public/protocols", params={**scope, "limit": 1}).json()
        assert page["total"] == 2
        assert [i["id"] for i in page["items"]] == [str(pid_a)]
        page = client.get(
            "/api/public/protocols", params={**scope, "limit": 1, "offset": 1}
        ).json()
        assert [i["id"] for i in page["items"]] == [str(pid_b)]
        ws = client.get("/api/public/protocols", params={**scope, "semester": "ws-2026"}).json()
        assert [i["id"] for i in ws["items"]] == [str(pid_a)]
        ws25 = client.get("/api/public/protocols", params={**scope, "semester": "ws-2025"})
        assert [i["id"] for i in ws25.json()["items"]] == [str(pid_b)]
        year = client.get("/api/public/protocols", params={**scope, "year": 2026}).json()
        assert year["total"] == 2
        semesters = client.get("/api/public/protocols/semesters", params=scope)
        assert semesters.headers["X-Robots-Tag"] == "noindex"
        assert semesters.json() == [{"key": "ws-2026", "count": 1}, {"key": "ws-2025", "count": 1}]
        assert (
            client.get("/api/public/protocols", params={"semester": "winter"}).status_code == 422
        )


async def _audit(maker: async_sessionmaker[AsyncSession], target: uuid.UUID) -> list[AuditEntry]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(AuditEntry)
                    .where(AuditEntry.target_id == str(target))
                    .order_by(AuditEntry.id)
                )
            ).all()
        )


async def test_switch_on_backfills_and_audits(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The switch to public builds the missing public versions and audits the change.

    The protocol was finalized while the gremium was private and has no non-public TOP,
    so no public version exists yet. Without Redis the backfill runs inline, and the
    protocol is public at once. The switch off hides it at once.
    """
    storage = _Storage()
    gremium_id, _, protocol_id = await _seed(maker, public=False, non_public_item=False)
    await _finalize(maker, protocol_id, storage)
    async with maker() as session:
        row = await session.get(Protocol, protocol_id)
        assert row is not None
        assert row.public_content is None
        assert row.public_pdf_storage_key is None

    with TestClient(api) as client:
        _enter(client, api, storage)
        preview = client.get(f"/api/admin/gremien/{gremium_id}/public-preview").json()
        assert preview == {"finalCount": 1, "missingCount": 1}
        assert client.get(f"/api/admin/gremien/{uuid.uuid4()}/public-preview").status_code == 404

        res = client.patch(f"/api/admin/gremien/{gremium_id}", json={"protocolsPublic": True})
        assert res.status_code == 200
        assert res.json()["protocolsPublic"] is True
        detail = client.get(f"/api/public/protocols/{protocol_id}")
        assert detail.status_code == 200
        assert detail.json()["tops"][0]["markdown"] == PUBLIC_BODY
        _assert_no_names(detail.json())
        preview = client.get(f"/api/admin/gremien/{gremium_id}/public-preview").json()
        assert preview == {"finalCount": 1, "missingCount": 0}

        client.patch(f"/api/admin/gremien/{gremium_id}", json={"protocolsPublic": False})
        assert client.get(f"/api/public/protocols/{protocol_id}").status_code == 404

    entries = [e for e in await _audit(maker, gremium_id) if e.action == "config_change"]
    flags = [e.data for e in entries if e.data.get("field") == "protocolsPublic"]
    assert flags == [
        {"field": "protocolsPublic", "old": False, "new": True},
        {"field": "protocolsPublic", "old": True, "new": False},
    ]


async def test_withhold_toggle_and_finalize_option(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The withhold toggle and the finalize option each write one publication entry.

    The same value again writes no second entry. A Markdown change on a final protocol
    stays refused.
    """
    storage = _Storage()
    _, meeting_id, protocol_id = await _seed(maker)

    with TestClient(api) as client:
        _enter(client, api, storage)
        out = client.get(f"/api/meetings/{meeting_id}/protocol").json()
        assert out["gremiumProtocolsPublic"] is True
        assert out["publicWithheld"] is False
        fin = client.post(
            f"/api/protocols/{protocol_id}/finalize", json={"publicWithheld": True}
        )
        assert fin.status_code == 200, fin.text
        assert fin.json()["publicWithheld"] is True
        assert client.get(f"/api/public/protocols/{protocol_id}").status_code == 404

        res = client.patch(f"/api/protocols/{protocol_id}", json={"publicWithheld": False})
        assert res.status_code == 200
        assert res.json()["publicWithheld"] is False
        assert res.json()["status"] == "final"
        assert client.get(f"/api/public/protocols/{protocol_id}").status_code == 200
        client.patch(f"/api/protocols/{protocol_id}", json={"publicWithheld": False})
        assert (
            client.patch(f"/api/protocols/{protocol_id}", json={"markdown": "x"}).status_code
            == 409
        )
        assert client.patch(f"/api/protocols/{protocol_id}", json={}).status_code == 422

    entries = await _audit(maker, protocol_id)
    finalize = [e for e in entries if e.action == "protocol_finalize"]
    assert finalize[0].data["publicWithheld"] is True
    publication = [e for e in entries if e.action == "protocol_publication"]
    assert [(e.data["old"], e.data["new"]) for e in publication] == [(False, True), (True, False)]


async def test_draft_patch_with_markdown_and_withheld(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    _, _, protocol_id = await _seed(maker)
    with TestClient(api) as client:
        _enter(client, api, None)
        res = client.patch(
            f"/api/protocols/{protocol_id}",
            json={"markdown": "Freitext", "publicWithheld": True},
        )
        assert res.status_code == 200
        assert res.json()["markdown"] == "Freitext"
        assert res.json()["publicWithheld"] is True


async def test_free_text_protocol_without_storage(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    """A meeting without agenda items publishes its free text; without storage no PDF."""
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        gremium = Gremium(name=f"F {tag}", slug=f"f-{tag}", protocols_public=True)
        session.add(gremium)
        await session.flush()
        meeting = Meeting(gremium_id=gremium.id, title="Klausur", status="closed")
        session.add(meeting)
        await session.flush()
        protocol = Protocol(
            meeting_id=meeting.id, gremium_id=gremium.id, status="draft", markdown="Notizen"
        )
        session.add(protocol)
        await session.commit()
        protocol_id = protocol.id
    async with maker() as session:
        svc = ProtocolService(session)
        await svc.start_finalize(protocol_id, actor="a")
        await svc.finalize(protocol_id, now=datetime.now(UTC))

    with TestClient(api) as client:
        _enter(client, api, None)
        data = client.get(f"/api/public/protocols/{protocol_id}").json()
        assert data["markdown"] == "Notizen"
        assert data["tops"] == []
        assert data["hasPdf"] is False
        assert data["date"] == datetime.now(UTC).date().isoformat()
        assert client.get(f"/api/public/protocols/{protocol_id}/pdf").status_code == 404


async def test_withheld_draft_stays_withheld_on_plain_finalize(
    api: FastAPI, maker: async_sessionmaker[AsyncSession]
) -> None:
    """A draft held back with PATCH stays held back when finalize sends no option."""
    _, _, protocol_id = await _seed(maker)
    with TestClient(api) as client:
        _enter(client, api, _Storage())
        held = client.patch(f"/api/protocols/{protocol_id}", json={"publicWithheld": True})
        assert held.json()["publicWithheld"] is True
        fin = client.post(f"/api/protocols/{protocol_id}/finalize")
        assert fin.status_code == 200, fin.text
        assert fin.json()["publicWithheld"] is True
        assert client.get(f"/api/public/protocols/{protocol_id}").status_code == 404
        nul = client.get("/api/public/protocols?q=%00")
        assert nul.status_code == 422
        assert nul.headers["X-Robots-Tag"] == "noindex"
    entries = await _audit(maker, protocol_id)
    assert [e.data["publicWithheld"] for e in entries if e.action == "protocol_finalize"] == [True]
    assert len([e for e in entries if e.action == "protocol_publication"]) == 1
