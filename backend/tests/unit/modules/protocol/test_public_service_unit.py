"""Unit tests of the public-version paths of `ProtocolService` (no database).

They cover the snapshot collection in `_assemble_from_agenda`, the finalize branch
of a public gremium, the hold-back switch with its audit entry, and the backfill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.audit.actions import AuditAction
from app.modules.files.storage import StorageError
from app.modules.protocol import service as protocol_service_mod
from app.modules.protocol.models import Protocol
from app.modules.protocol.public import PublicSnapshot, PublicTop
from app.modules.protocol.service import (
    ProtocolService,
    protocol_public_storage_key,
    protocol_storage_key,
)
from app.settings import get_settings
from app.shared.errors import BadRequestError, ServiceUnavailableError
from tests._support.protocol_fakes import FakeSession, FakeStorage, result

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
PID = uuid4()
MID = uuid4()
GID = uuid4()


def _protocol(**over: Any) -> Protocol:
    proto = Protocol(
        meeting_id=MID,
        gremium_id=GID,
        markdown=over.pop("markdown", ""),
        status=over.pop("status", "final"),
        cd_variant="stupa",
    )
    proto.id = PID
    proto.public_withheld = over.pop("public_withheld", False)
    for key, val in over.items():
        setattr(proto, key, val)
    return proto


def _service(session: Any, **infra: Any) -> ProtocolService:
    return ProtocolService(session, settings=get_settings(), **infra)


class _Voting:
    """Stand-in for VotingService: answers `get` with prepared vote views."""

    views: dict[UUID, Any] = {}

    def __init__(self, _session: Any) -> None: ...

    async def get(self, vote_id: UUID) -> Any:
        return self.views[vote_id]


def _view(question: str, status: str = "closed") -> SimpleNamespace:
    return SimpleNamespace(
        question=question,
        status=status,
        result="passed" if status == "closed" else None,
        majority_rule="simple",
        secret=False,
        guests_vote=False,
        tally=SimpleNamespace(counts={"ja": 4, "nein": 1}),
    )


async def test_assemble_collects_public_tops(monkeypatch: pytest.MonkeyPatch) -> None:
    pub_item = SimpleNamespace(id=uuid4(), title="Haushalt", body="Text", non_public=False)
    np_item = SimpleNamespace(id=uuid4(), title="Personal", body="Geheim", non_public=True)
    empty_item = SimpleNamespace(id=uuid4(), title=None, body="  ", non_public=False)
    closed = SimpleNamespace(id=uuid4())
    draft = SimpleNamespace(id=uuid4())
    in_body = SimpleNamespace(id=uuid4())
    _Voting.views = {
        closed.id: _view("Annehmen?"),
        draft.id: _view("Später?", status="draft"),
        in_body.id: _view("Schon im Text?"),
    }
    pub_item.body = "Text\n\n> [!abstimmung] **Schon im Text?**"
    monkeypatch.setattr(protocol_service_mod, "VotingService", _Voting)
    session = FakeSession(
        results=[
            result(pub_item, np_item, empty_item),
            result(closed, draft, in_body),
            result(),
        ]
    )
    tops: list[PublicTop] = []
    md = await _service(session)._assemble_from_agenda(MID, public=True, tops=tops)
    assert "Geheim" not in md
    assert [t.number for t in tops] == [1, 2, 3]
    assert tops[0].title == "Haushalt"
    # A vote already in the text as a snippet still shows its result in the list.
    assert [d.question for d in tops[0].decisions] == ["Annehmen?", "Schon im Text?"]
    assert [d.in_text for d in tops[0].decisions] == [False, True]
    assert md.count("Schon im Text?") == 1
    assert tops[0].decisions[0].counts == {"ja": 4, "nein": 1}
    assert tops[1].non_public is True and tops[1].title is None and tops[1].markdown is None
    assert tops[2].title == "Tagesordnungspunkt" and tops[2].markdown is None


async def test_finalize_public_gremium_renders_public_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proto = _protocol(status="rendering")
    gremium = SimpleNamespace(id=GID, protocols_public=True)
    session = FakeSession(store={GID: gremium}, results=[result(proto)])
    svc = _service(session, storage=FakeStorage())
    mailed: list[bytes | None] = []

    async def _has_non_public(_mid: UUID) -> bool:
        return False

    async def _build(protocol: Protocol, *, public: bool = False, snapshot: Any = None) -> str:
        if snapshot is not None:
            snapshot.tops.append(PublicTop(number=1, title="A", markdown="x"))
        return "public" if public else "internal"

    async def _render(protocol: Protocol, markdown: str, *, public: bool = False) -> bytes:
        if public:
            protocol.public_pdf_storage_key = protocol_public_storage_key(protocol.id)
        else:
            protocol.pdf_storage_key = protocol_storage_key(protocol.id)
        return f"%PDF-{markdown}".encode()

    async def _send(protocol: Protocol, pdf: bytes | None) -> None:
        mailed.append(pdf)

    monkeypatch.setattr(svc, "_has_non_public", _has_non_public)
    monkeypatch.setattr(svc, "_build_document", _build)
    monkeypatch.setattr(svc, "_render_pdf", _render)
    monkeypatch.setattr(svc, "_send", _send)
    out = await svc.finalize(PID, now=NOW)

    assert out.status == "final"
    assert out.gremium_protocols_public is True
    assert proto.public_content is not None
    assert proto.public_content["tops"][0]["title"] == "A"
    assert proto.public_search_text == "A\nx"
    assert proto.public_pdf_size == len(b"%PDF-public")
    # Without a non-public TOP the mail keeps the internal PDF, as before.
    assert mailed == [b"%PDF-internal"]
    assert isinstance(svc.storage, FakeStorage)
    assert {k for k, _n, _ct in svc.storage.puts} == {
        protocol_storage_key(PID),
        protocol_public_storage_key(PID),
    }


async def test_set_public_withheld_audits_a_change_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries: list[dict[str, Any]] = []

    async def _record(_session: Any, **kw: Any) -> None:
        entries.append(kw)

    monkeypatch.setattr(protocol_service_mod, "audit_record", _record)
    proto = _protocol()
    session = FakeSession(results=[result(proto), result(proto)])
    svc = _service(session)
    out = await svc.set_public_withheld(PID, True, actor="sub-1")
    assert out.public_withheld is True
    assert entries[0]["action"] == AuditAction.PROTOCOL_PUBLICATION
    assert entries[0]["data"]["old"] is False and entries[0]["data"]["new"] is True
    await svc.set_public_withheld(PID, True, actor="sub-1")
    assert len(entries) == 1


def _finalize_fakes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    async def _record(_session: Any, **kw: Any) -> None:
        entries.append(kw)

    class _Guests:
        def __init__(self, _session: Any) -> None: ...

        async def pseudonymize(self, _mid: UUID) -> None: ...

    monkeypatch.setattr(protocol_service_mod, "audit_record", _record)
    monkeypatch.setattr("app.modules.livevote.guests.GuestService", _Guests)
    return entries


async def _start(withheld_before: bool, option: bool | None) -> Protocol:
    proto = _protocol(status="draft", public_withheld=withheld_before)
    meeting = SimpleNamespace(id=MID, status="closed")
    session = FakeSession(store={MID: meeting}, results=[result(proto)])
    await _service(session).start_finalize(PID, actor="a", public_withheld=option)
    return proto


async def test_start_finalize_sets_and_audits_the_withhold_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _finalize_fakes(monkeypatch)
    proto = await _start(False, True)
    assert proto.public_withheld is True
    actions = [e["action"] for e in entries]
    assert actions == [AuditAction.PROTOCOL_PUBLICATION, AuditAction.PROTOCOL_FINALIZE]
    assert (entries[0]["data"]["old"], entries[0]["data"]["new"]) == (False, True)
    assert entries[1]["data"]["publicWithheld"] is True


async def test_start_finalize_without_option_keeps_a_withheld_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A draft held back earlier stays held back on a plain finalize (no option)."""
    entries = _finalize_fakes(monkeypatch)
    proto = await _start(True, None)
    assert proto.public_withheld is True
    assert [e["action"] for e in entries] == [AuditAction.PROTOCOL_FINALIZE]
    assert entries[0]["data"]["publicWithheld"] is True
    # The same value again writes no publication entry either.
    entries.clear()
    proto = await _start(True, True)
    assert [e["action"] for e in entries] == [AuditAction.PROTOCOL_FINALIZE]


async def test_start_finalize_can_release_a_withheld_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _finalize_fakes(monkeypatch)
    proto = await _start(True, False)
    assert proto.public_withheld is False
    assert (entries[0]["data"]["old"], entries[0]["data"]["new"]) == (True, False)


async def test_gremien_missing_public_lists_the_gremien() -> None:
    gid = uuid4()
    statements: list[str] = []
    session = FakeSession(results=[result(gid), result()])
    original = session.scalars

    async def _scalars(stmt: Any) -> Any:
        statements.append(str(stmt))
        return await original(stmt)

    session.scalars = _scalars  # type: ignore[method-assign]
    with_storage = _service(session, storage=FakeStorage(), typst=object())
    assert await with_storage.gremien_missing_public() == [gid]
    assert "public_pdf_storage_key" in statements[0]
    assert await _service(session).gremien_missing_public() == []
    assert "public_pdf_storage_key" not in statements[1]


async def test_backfill_counts_each_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [uuid4(), uuid4(), uuid4()]
    session = FakeSession(results=[result(*ids)])
    rolled: list[int] = []

    async def _rollback() -> None:
        rolled.append(1)

    session.rollback = _rollback  # type: ignore[attr-defined]
    svc = _service(session, storage=FakeStorage(), typst=object())
    outcomes = {
        ids[0]: None,
        ids[1]: ServiceUnavailableError("later"),
        ids[2]: BadRequestError("broken"),
    }

    async def _one(pid: UUID) -> None:
        err = outcomes[pid]
        if err is not None:
            raise err

    counted: list[UUID] = []

    async def _count(pid: UUID) -> None:
        counted.append(pid)

    monkeypatch.setattr(svc, "_backfill_one", _one)
    monkeypatch.setattr(svc, "_count_render_failure", _count)
    res = await svc.backfill_public(GID)
    assert (res.done, res.transient, res.failed) == (1, 1, 1)
    assert len(rolled) == 2
    # Only the permanent failure counts; a transient one retries later.
    assert counted == [ids[2]]


async def test_count_render_failure_warns_once_at_the_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.modules.protocol.service import PUBLIC_RENDER_MAX_FAILURES

    proto = _protocol(public_render_failures=PUBLIC_RENDER_MAX_FAILURES - 2)
    session = FakeSession(store={PID: proto})
    svc = _service(session)
    with caplog.at_level("WARNING", logger="app.protocol"):
        await svc._count_render_failure(PID)
        assert not caplog.records
        await svc._count_render_failure(PID)
        assert len(caplog.records) == 1
        await svc._count_render_failure(PID)
        assert len(caplog.records) == 1
    assert proto.public_render_failures == PUBLIC_RENDER_MAX_FAILURES + 1
    assert session.committed == 3
    # A missing protocol is a no-op.
    await _service(FakeSession())._count_render_failure(uuid4())


async def test_heal_backfill_skips_protocols_at_the_failure_limit() -> None:
    session = FakeSession(results=[result(), result()])
    statements: list[str] = []
    original = session.scalars

    async def _scalars(stmt: Any) -> Any:
        statements.append(str(stmt))
        return await original(stmt)

    session.scalars = _scalars  # type: ignore[method-assign]
    await _service(session).backfill_public(GID, retry_failed=False)
    await _service(session).backfill_public(GID)
    assert "public_render_failures" in statements[0]
    assert "public_render_failures" not in statements[1]


async def test_backfill_without_storage_only_needs_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(results=[result()])
    statements: list[str] = []
    original = session.scalars

    async def _scalars(stmt: Any) -> Any:
        statements.append(str(stmt))
        return await original(stmt)

    session.scalars = _scalars  # type: ignore[method-assign]
    res = await _service(session).backfill_public(GID)
    assert res.done == 0
    assert "public_pdf_storage_key" not in statements[0]


def _wire_build(svc: ProtocolService, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    rendered: list[str] = []

    async def _build(protocol: Protocol, *, public: bool = False, snapshot: Any = None) -> str:
        assert public is True
        snapshot.markdown = "Freitext"
        return "md"

    async def _render(protocol: Protocol, markdown: str, *, public: bool = False) -> bytes:
        rendered.append(markdown)
        protocol.public_pdf_storage_key = protocol_public_storage_key(protocol.id)
        return b"%PDF-new"

    monkeypatch.setattr(svc, "_build_document", _build)
    monkeypatch.setattr(svc, "_render_pdf", _render)
    return rendered


async def test_backfill_one_renders_a_missing_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    proto = _protocol(public_render_failures=2)
    storage = FakeStorage()
    svc = _service(FakeSession(results=[result(proto)]), storage=storage)
    rendered = _wire_build(svc, monkeypatch)
    await svc._backfill_one(PID)
    assert rendered == ["md"]
    assert proto.public_render_failures == 0
    assert proto.public_content is not None and proto.public_content["markdown"] == "Freitext"
    assert proto.public_pdf_size == len(b"%PDF-new")
    assert storage.blobs[protocol_public_storage_key(PID)] == b"%PDF-new"


async def test_backfill_one_reads_the_size_of_an_existing_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = protocol_public_storage_key(PID)
    proto = _protocol(public_pdf_storage_key=key, public_pdf_size=None)
    storage = FakeStorage()
    storage.blobs[key] = b"%PDF-old"
    svc = _service(FakeSession(results=[result(proto)]), storage=storage)
    rendered = _wire_build(svc, monkeypatch)
    await svc._backfill_one(PID)
    assert rendered == []
    assert proto.public_pdf_size == len(b"%PDF-old")


async def test_backfill_one_survives_a_storage_read_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = protocol_public_storage_key(PID)
    proto = _protocol(public_pdf_storage_key=key, public_pdf_size=None)

    class _Failing(FakeStorage):
        async def get(self, key: str) -> bytes:
            raise StorageError("down")

    svc = _service(FakeSession(results=[result(proto)]), storage=_Failing())
    _wire_build(svc, monkeypatch)
    await svc._backfill_one(PID)
    assert proto.public_content is not None
    assert proto.public_pdf_size is None


async def test_backfill_one_skips_a_finished_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    proto = _protocol(
        public_content=PublicSnapshot().model_dump(mode="json", by_alias=True),
        public_pdf_storage_key=protocol_public_storage_key(PID),
    )
    session = FakeSession(results=[result(proto)])
    svc = _service(session, storage=FakeStorage())
    rendered = _wire_build(svc, monkeypatch)
    await svc._backfill_one(PID)
    assert rendered == []
    assert session.committed == 1


async def test_to_out_reads_the_gremium_flag() -> None:
    proto = _protocol(status="draft", public_withheld=True)
    session = FakeSession(store={GID: SimpleNamespace(protocols_public=True)})
    out = await _service(session)._to_out(proto)
    assert out.public_withheld is True
    assert out.gremium_protocols_public is True
    out = await _service(FakeSession())._to_out(proto)
    assert out.gremium_protocols_public is False

