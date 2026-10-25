"""Unit tests for ProtocolService: lifecycle, vote embedding and finalize.

The suite runs without a database, typst, MinIO or Redis. `session.get` reads from a
store and `execute` reads from an ordered result queue, which gives the branch
coverage. The integration suite covers the real DB constraints, the UNIQUE meeting_id
and the UNIQUE vote_ref.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.admin.models import Gremium
from app.modules.livevote.models import Meeting
from app.modules.pdf.typst_client import TypstError
from app.modules.protocol import service as protocol_service_mod
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import ProtocolService, protocol_storage_key
from app.settings import get_settings
from app.shared.errors import ConflictError, NotFoundError, ServiceUnavailableError
from tests._support.pdf_fakes import FakeTypst
from tests._support.protocol_fakes import FakeMailQueue, FakeSession, FakeStorage, result

NOW = datetime(2026, 6, 12, 19, 0, tzinfo=UTC)
PID = uuid4()
MID = uuid4()
GID = uuid4()
VID = uuid4()


def _protocol(**over: Any) -> Protocol:
    proto = Protocol(
        meeting_id=MID,
        gremium_id=GID,
        markdown=over.pop("markdown", "# Body"),
        status=over.pop("status", "draft"),
        cd_variant=over.pop("cd_variant", "stupa"),
    )
    proto.id = PID
    for key, val in over.items():
        setattr(proto, key, val)
    return proto


def _meeting() -> SimpleNamespace:
    return SimpleNamespace(
        id=MID, gremium_id=GID, title="StuPa-Sitzung", date=date(2026, 6, 12)
    )


def _gremium(cd_variant: str = "stupa") -> SimpleNamespace:
    return SimpleNamespace(
        id=GID, name="STUPA", slug="stupa", cd_variant=cd_variant, protocols_public=False
    )


def _real_meeting() -> Meeting:
    meeting = Meeting(gremium_id=GID, title="StuPa-Sitzung", date=date(2026, 6, 12))
    meeting.id = MID
    return meeting


def _real_gremium() -> Gremium:
    gremium = Gremium(name="StuPa", slug="stupa")
    gremium.id = GID
    return gremium


def _vote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": VID,
        "application_id": uuid4(),
        "meeting_id": MID,
        "eligible_group": "stupa",
        "config": {
            "options": ["yes", "no", "abstain"],
            "majorityRule": "simple",
            "secret": False,
            "tieBreak": "rejected",
            "abstainCountsQuorum": True,
            "quorum": None,
        },
        "eligible_count": 10,
        "opens_at": None,
        "closes_at": None,
        "closed_at": None,
        "status": "closed",
        "result": "passed",
    }
    base.update(over)
    return SimpleNamespace(**base)


SETTINGS_BASE = get_settings().public_base_url.rstrip("/")


def _service(session: Any, **infra: Any) -> ProtocolService:
    return ProtocolService(session, settings=get_settings(), **infra)


def test_insert_values_inherits_cd_variant_and_gremium() -> None:
    meeting = _real_meeting()
    values = ProtocolService._insert_values(meeting, "asta", "p1")
    assert values == {
        "meeting_id": MID,
        "gremium_id": GID,
        "markdown": "",
        "status": "draft",
        "author": "p1",
        "cd_variant": "asta",
    }


def test_insert_values_without_gremium_has_null_variant() -> None:
    values = ProtocolService._insert_values(_real_meeting(), None, None)
    assert values["cd_variant"] is None and values["gremium_id"] == GID


async def test_get_or_create_new_reselects_after_insert() -> None:
    """A new protocol is inserted and selected again.

    The execute order is ``_by_meeting`` (empty), the ignored ``pg_insert``, then
    ``_by_meeting`` with the new row.
    """
    created = _protocol(markdown="", status="draft")
    session = FakeSession(
        store={MID: _real_meeting(), GID: _real_gremium()},
        results=[result(), result(), result(created)],
    )
    out = await _service(session).get_or_create(MID, author="p1")
    assert out.status == "draft"
    assert out.markdown == ""
    assert session.committed == 1


async def test_get_or_create_returns_existing_idempotent() -> None:
    """An existing protocol is a pure read, with no insert and no commit."""
    existing = _protocol(markdown="# schon da")
    session = FakeSession(results=[result(existing)])
    out = await _service(session).get_or_create(MID)
    assert out.markdown == "# schon da"
    assert session.committed == 0


async def test_get_or_create_concurrent_insert_reselects_winner() -> None:
    """A parallel POST makes the own ON CONFLICT insert a no-op.

    The re-select then returns the winner row.
    """
    winner = _protocol(markdown="# vom Parallel-Request")
    session = FakeSession(
        store={MID: _real_meeting(), GID: _real_gremium()},
        results=[result(), result(), result(winner)],
    )
    out = await _service(session).get_or_create(MID)
    assert out.markdown == "# vom Parallel-Request"


async def test_get_or_create_blocked_before_start() -> None:
    """Before the start (`planned`) no protocol appears. Only the start creates it."""
    meeting = _real_meeting()
    meeting.status = "planned"
    session = FakeSession(
        store={MID: meeting, GID: _real_gremium()}, results=[result()]
    )
    with pytest.raises(ConflictError):
        await _service(session).get_or_create(MID)
    assert session.committed == 0


async def test_get_or_create_unknown_meeting_404() -> None:
    session = FakeSession(store={}, results=[result()])
    with pytest.raises(NotFoundError):
        await _service(session).get_or_create(MID)


async def test_get_or_create_vanished_after_insert_404() -> None:
    """Defensive: a row that vanishes before the re-select gives 404, not a None deref.

    The fake session serves no existing row, the insert, and an empty re-select.
    """
    session = FakeSession(
        store={MID: _real_meeting(), GID: _real_gremium()},
        results=[result(), result(), result()],
    )
    with pytest.raises(NotFoundError):
        await _service(session).get_or_create(MID)


async def test_update_markdown_ok() -> None:
    session = FakeSession(results=[result(_protocol())])
    out = await _service(session).update_markdown(PID, "# Neu")
    assert out.markdown == "# Neu"
    assert session.committed == 1


async def test_update_markdown_final_conflict() -> None:
    session = FakeSession(results=[result(_protocol(status="final"))])
    with pytest.raises(ConflictError):
        await _service(session).update_markdown(PID, "# Neu")


async def test_update_markdown_unknown_protocol_404() -> None:
    """An unknown protocol gives 404."""
    session = FakeSession(results=[result()])
    with pytest.raises(NotFoundError):
        await _service(session).update_markdown(PID, "# Neu")


async def test_embed_votes_appends_snippet_and_ref() -> None:
    """An embedded vote appends a snippet and writes the reference.

    The snippet has no "Ergebnis" line, because the tally box carries the result. The
    fake session serves ``_get``, no existing refs, the inserted ref id,
    ``VotingService._get_vote`` and the ballots for ``VotingService._aggregate``.
    """
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(
        store={VID: _vote()},
        results=[
            result(proto),
            result(),
            result(uuid4()),
            result(_vote()),
            result("yes", "yes", "no"),
        ],
    )
    out = await _service(session).embed_votes(PID, [VID])
    assert "> [!abstimmung]" in out.markdown
    assert "Ergebnis" not in out.markdown
    assert "yes: 2, no: 1" in out.markdown
    assert session.committed == 1


async def test_embed_votes_idempotent_skips_referenced() -> None:
    """A vote that is already referenced leaves the Markdown unchanged."""
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(results=[result(proto), result(VID)])
    out = await _service(session).embed_votes(PID, [VID])
    assert out.markdown == "# TOP 1"


async def test_embed_votes_concurrent_ref_skips_snippet() -> None:
    """A parallel insert wins: ON CONFLICT returns nothing, so no snippet doubles.

    The insert returns nothing, because a parallel insert won the conflict, so the
    Markdown stays unchanged.
    """
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(
        store={VID: _vote()},
        results=[
            result(proto),
            result(),
            result(),
        ],
    )
    out = await _service(session).embed_votes(PID, [VID])
    assert out.markdown == "# TOP 1"


async def test_embed_votes_unknown_vote_404() -> None:
    session = FakeSession(store={}, results=[result(_protocol()), result()])
    with pytest.raises(NotFoundError):
        await _service(session).embed_votes(PID, [VID])


async def test_embed_votes_on_final_conflict() -> None:
    session = FakeSession(results=[result(_protocol(status="final"))])
    with pytest.raises(ConflictError):
        await _service(session).embed_votes(PID, [VID])


async def test_finalize_renders_stores_and_mails() -> None:
    """The finalization renders, stores and mails the protocol.

    The fake session serves the empty agenda, the members (the base of the union) and an
    empty mail list. The PDF travels as an attachment, because a link to the API needs a
    login and a meeting right, which the recipients do not have. The mail links the
    meeting page, which holds the protocol, and names no public version for a Gremium
    that does not publish its protocols.
    """
    proto = _protocol()
    storage = FakeStorage()
    typst = FakeTypst(pdf=b"%PDF-1.4 ok")
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium("stupa")},
        results=[result(proto), result(), result("a@x.de", "b@x.de"), result()],
    )
    out = await _service(
        session, storage=storage, typst=typst, mail_queue=mail
    ).finalize(PID, now=NOW)

    assert out.status == "final"
    assert out.sent_at == NOW
    assert proto.pdf_storage_key == protocol_storage_key(PID)
    assert storage.puts and storage.puts[0][2] == "application/pdf"
    assert typst.calls and typst.calls[0][1] == "protocol-stupa"
    assert out.pdf_url is not None
    assert len(mail.sent) == 1
    assert mail.sent[0].to == ("a@x.de", "b@x.de")
    assert [a.filename for a in mail.sent[0].attachments] == ["protokoll.pdf"]
    assert mail.sent[0].attachments[0].content.startswith(b"%PDF")
    assert f"Protokoll öffnen: {SETTINGS_BASE}/meetings/{MID}" in mail.sent[0].text
    assert f'href="{SETTINGS_BASE}/meetings/{MID}"' in (mail.sent[0].html or "")
    assert "/protokolle/" not in mail.sent[0].text


async def test_protocol_mail_links_the_public_version_when_public() -> None:
    """A protocol on the public page: the mail links the public version too.

    An external list address cannot log in, so the public link is the only link that
    it can open.
    """
    proto = _protocol(status="final", public_withheld=False, public_content={"tops": []})
    gremium = _gremium("stupa")
    gremium.protocols_public = True
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: gremium},
        results=[result("a@x.de"), result()],
    )
    await _service(session, mail_queue=mail)._send(proto, None)

    assert len(mail.sent) == 1
    text = mail.sent[0].text
    assert f"Öffentliche Fassung: {SETTINGS_BASE}/protokolle/{PID}" in text
    assert f"Protokoll öffnen: {SETTINGS_BASE}/meetings/{MID}" in text


async def test_protocol_mail_hides_a_withheld_public_version() -> None:
    """A held-back protocol is not public, so the mail names no public version."""
    proto = _protocol(status="final", public_withheld=True, public_content={"tops": []})
    gremium = _gremium("stupa")
    gremium.protocols_public = True
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: gremium},
        results=[result("a@x.de"), result()],
    )
    await _service(session, mail_queue=mail)._send(proto, None)

    assert "/protokolle/" not in mail.sent[0].text


async def test_the_design_never_decides_the_document_shape() -> None:
    """The shape comes from the document, the design only from the Gremium.

    Passing the design to typst as the shape once put every application of a
    protocol-designed Gremium out as a meeting protocol. One Gremium renders both kinds,
    so the two must stay separate: `cd_variant` picks `protocol-stupa` here, and it is
    the protocol shape because a protocol is what is being rendered.
    """
    typst = FakeTypst(pdf=b"%PDF")
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium("stupa")},
        results=[result(_protocol()), result(), result(), result()],
    )
    await _service(session, storage=FakeStorage(), typst=typst).finalize(PID, now=NOW)

    assert typst.calls[0][1] == "protocol-stupa"


async def test_finalize_uploads_and_mails_only_after_commit() -> None:
    """The storage put and the mail enqueue run after the commit.

    The fakes count the commit and record the put and the enqueue only after it. The
    test checks the committed end state. The PDF is in the storage, the mail is queued
    and the commit ran.

    Exactly one put (single render) and one mail run, both on the post-commit path.
    """
    proto = _protocol()
    storage = FakeStorage()
    typst = FakeTypst(pdf=b"%PDF-1.4 ok")
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium("stupa")},
        results=[result(proto), result(), result("a@x.de"), result()],
    )
    await _service(
        session, storage=storage, typst=typst, mail_queue=mail
    ).finalize(PID, now=NOW)
    assert session.committed == 1
    assert [p[0] for p in storage.puts] == [protocol_storage_key(PID)]
    assert len(mail.sent) == 1


async def test_finalize_storage_error_after_commit_raises_503() -> None:
    """A transient failure of the post-commit storage `put` gives a 503.

    The protocol is already committed as `final`, so a retry is an idempotent no-op.

    The commit ran before the storage put.
    """

    class _BoomStorage(FakeStorage):
        async def put(self, key: str, data: bytes, content_type: str) -> None:
            from app.modules.files.storage import StorageError

            raise StorageError("minio down")

    proto = _protocol()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result()],
    )
    with pytest.raises(ServiceUnavailableError):
        await _service(
            session, storage=_BoomStorage(), typst=FakeTypst()
        ).finalize(PID, now=NOW)
    assert session.committed == 1
    assert proto.status == "final"


async def test_finalize_without_storage_degrades_but_mails() -> None:
    """Without storage the render is skipped, and the mail goes out without a PDF."""
    proto = _protocol()
    typst = FakeTypst()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result(), result("a@x.de"), result()],
    )
    out = await _service(session, storage=None, typst=typst, mail_queue=mail).finalize(
        PID, now=NOW
    )
    assert out.status == "final"
    assert out.pdf_url is None
    assert proto.pdf_storage_key is None
    assert typst.calls == []
    assert len(mail.sent) == 1 and mail.sent[0].attachments == ()


async def test_finalize_idempotent_when_already_final() -> None:
    """A final protocol comes back with a URL freshly signed from the existing key."""
    proto = _protocol(status="final", pdf_storage_key="pdf/protocol/x.pdf")
    storage = FakeStorage()
    typst = FakeTypst()
    mail = FakeMailQueue()
    session = FakeSession(results=[result(proto)])
    out = await _service(
        session, storage=storage, typst=typst, mail_queue=mail
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert out.pdf_url is not None
    assert storage.puts == [] and typst.calls == [] and mail.sent == []


async def test_finalize_render_error_raises_503() -> None:
    """A render error gives 503, and the draft stays."""
    proto = _protocol()
    typst = FakeTypst(error=TypstError("boom", retryable=True))
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()}, results=[result(proto)]
    )
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage=FakeStorage(), typst=typst).finalize(
            PID, now=NOW
        )
    assert proto.status == "draft"


async def test_finalize_no_recipients_skips_mail() -> None:
    """An empty mail list sends no mail."""
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result()],
    )
    out = await _service(
        session, storage=FakeStorage(), typst=FakeTypst(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert mail.sent == []


async def test_finalize_members_receive_even_without_maillist() -> None:
    """An empty mail_list still sends to the active Gremium members.

    The members are always the base of the recipient union.

    The fake session serves ``_get``, no agenda items, two members and an empty mail
    list.
    """
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),
            result(),
            result("a@x.de", "b@x.de"),
            result(),
        ],
    )
    out = await _service(
        session, storage=FakeStorage(), typst=FakeTypst(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert len(mail.sent) == 1
    assert mail.sent[0].to == ("a@x.de", "b@x.de")


async def test_finalize_without_mail_queue_skips_send() -> None:
    proto = _protocol()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()}, results=[result(proto)]
    )
    out = await _service(
        session, storage=FakeStorage(), typst=FakeTypst(), mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert out.pdf_url is not None


async def test_finalize_deduplicates_recipients_across_lists() -> None:
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result(), result(), result(["a@x", "b@x"], ["b@x", "c@x"])],
    )
    await _service(
        session, storage=FakeStorage(), typst=FakeTypst(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert mail.sent[0].to == ("a@x", "b@x", "c@x")


async def test_pdf_url_is_app_relative_path_not_bucket_link() -> None:
    """`pdfUrl` points at the app stream (`/api/...`), never at a bucket or MinIO URL."""
    proto = _protocol(pdf_storage_key=protocol_storage_key(PID))
    session = FakeSession(results=[result(proto)])
    out = await _service(session, storage=FakeStorage()).update_markdown(PID, "x")
    assert out.pdf_url == f"/api/protocols/{PID}/pdf"
    assert "minio" not in (out.pdf_url or "")


async def test_get_pdf_bytes_streams_from_storage() -> None:
    proto = _protocol(pdf_storage_key=protocol_storage_key(PID))
    storage = FakeStorage()
    storage.blobs[protocol_storage_key(PID)] = b"%PDF-1.4 stream"
    session = FakeSession(results=[result(proto)])
    data = await _service(session, storage=storage).get_pdf_bytes(PID)
    assert data == b"%PDF-1.4 stream"


async def test_get_pdf_bytes_404_without_pdf() -> None:
    proto = _protocol(pdf_storage_key=None)
    session = FakeSession(results=[result(proto)])
    with pytest.raises(NotFoundError):
        await _service(session, storage=FakeStorage()).get_pdf_bytes(PID)


async def test_get_pdf_bytes_404_without_storage() -> None:
    proto = _protocol(pdf_storage_key=protocol_storage_key(PID))
    session = FakeSession(results=[result(proto)])
    with pytest.raises(NotFoundError):
        await _service(session, storage=None).get_pdf_bytes(PID)


def _closed_meeting(status: str = "closed") -> SimpleNamespace:
    return SimpleNamespace(id=MID, gremium_id=GID, status=status)


async def test_start_finalize_marks_rendering_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The start sets ``rendering``, audits, and commits before the enqueue."""
    calls: list[dict[str, Any]] = []

    async def _record(_session: Any, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(protocol_service_mod, "audit_record", _record)
    proto = _protocol()
    session = FakeSession(store={MID: _closed_meeting()}, results=[result(proto)])
    out = await _service(session).start_finalize(PID, actor="lead")
    assert out.status == "rendering" and proto.status == "rendering"
    assert session.committed == 1
    [entry] = calls
    assert entry["action"].value == "protocol_finalize"
    assert entry["actor"] == "lead"
    assert entry["target_id"] == str(PID)
    assert entry["data"] == {
        "meetingId": str(MID),
        "gremiumId": str(GID),
        "publicWithheld": False,
    }


@pytest.mark.parametrize("status", ["planned", "live"])
async def test_start_finalize_needs_a_closed_meeting(status: str) -> None:
    """No finalization while the meeting runs."""
    proto = _protocol()
    session = FakeSession(store={MID: _closed_meeting(status)}, results=[result(proto)])
    with pytest.raises(ConflictError) as ei:
        await _service(session).start_finalize(PID, actor="lead")
    assert ei.value.code == "meeting_not_closed"
    assert proto.status == "draft"
    assert session.committed == 0


@pytest.mark.parametrize("status", ["rendering", "final"])
async def test_start_finalize_only_once(status: str) -> None:
    """One finalization, also with several keepers.

    There is no double enqueue and no write.
    """
    proto = _protocol(status=status)
    session = FakeSession(store={MID: _closed_meeting()}, results=[result(proto)])
    with pytest.raises(ConflictError) as ei:
        await _service(session).start_finalize(PID, actor="lead")
    assert ei.value.code == "protocol_not_draft"
    assert session.committed == 0


async def test_revert_to_draft_resets_rendering() -> None:
    proto = _protocol(status="rendering")
    session = FakeSession(results=[result(proto)])
    await _service(session).revert_to_draft(PID)
    assert proto.status == "draft"
    assert session.committed == 1


async def test_revert_to_draft_keeps_final_untouched() -> None:
    proto = _protocol(status="final")
    session = FakeSession(results=[result(proto)])
    await _service(session).revert_to_draft(PID)
    assert proto.status == "final"
    assert session.committed == 0


async def test_update_markdown_while_rendering_conflict() -> None:
    """During the background render the content is frozen (409)."""
    session = FakeSession(results=[result(_protocol(status="rendering"))])
    with pytest.raises(ConflictError):
        await _service(session).update_markdown(PID, "# Neu")


async def test_embed_votes_while_rendering_conflict() -> None:
    session = FakeSession(results=[result(_protocol(status="rendering"))])
    with pytest.raises(ConflictError):
        await _service(session).embed_votes(PID, [VID])


async def test_finalize_from_rendering_completes() -> None:
    """The worker path: the status `rendering` renders through to `final`."""
    proto = _protocol(status="rendering")
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result(), result("a@x.de"), result()],
    )
    out = await _service(
        session, storage=FakeStorage(), typst=FakeTypst(), mail_queue=FakeMailQueue()
    ).finalize(PID, now=NOW)
    assert out.status == "final"


async def test_finalize_recipients_union_members_plus_maillist() -> None:
    """An extra mail list extends the member list.

    The result is a deduplicated union. The extra list never replaces the members.

    The fake session serves ``_get``, no agenda items, the active members and an extra
    mail list that repeats a member address.
    """
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),
            result(),
            result("member@x.de"),
            result(["extra@y.de", "member@x.de"]),
        ],
    )
    await _service(
        session, storage=FakeStorage(), typst=FakeTypst(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert len(mail.sent) == 1
    assert mail.sent[0].to == ("member@x.de", "extra@y.de")


async def test_get_by_meeting_reads_without_create() -> None:
    """Reload and poll path: reads the existing protocol and never creates one."""
    proto = _protocol(status="rendering")
    session = FakeSession(results=[result(proto)])
    out = await _service(session).get_by_meeting(MID)
    assert out.status == "rendering"
    assert session.added == [] and session.committed == 0


async def test_get_by_meeting_404_without_protocol() -> None:
    session = FakeSession(results=[result()])
    with pytest.raises(NotFoundError):
        await _service(session).get_by_meeting(MID)


async def test_delete_protocol_draft_ok() -> None:
    from app.modules.audit.models import AuditEntry

    proto = _protocol()
    session = FakeSession(results=[result(proto)])
    await _service(session).delete_protocol(PID, actor="p1")
    assert session.deleted == [proto]
    assert session.committed == 1
    entries = [o for o in session.added if isinstance(o, AuditEntry)]
    assert [e.action for e in entries] == ["protocol_delete"]
    assert entries[0].target_type == "protocol"
    assert entries[0].data == {"meetingId": str(MID), "gremiumId": str(GID)}


async def test_delete_protocol_final_conflict() -> None:
    session = FakeSession(results=[result(_protocol(status="final"))])
    with pytest.raises(ConflictError):
        await _service(session).delete_protocol(PID, actor="p1")
    assert session.deleted == []


async def test_delete_protocol_while_rendering_conflict() -> None:
    session = FakeSession(results=[result(_protocol(status="rendering"))])
    with pytest.raises(ConflictError):
        await _service(session).delete_protocol(PID, actor="p1")


async def test_delete_protocol_unknown_404() -> None:
    session = FakeSession(results=[result()])
    with pytest.raises(NotFoundError):
        await _service(session).delete_protocol(PID, actor="p1")
