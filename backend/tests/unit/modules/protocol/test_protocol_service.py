"""Unit tests for ProtocolService (T-22): lifecycle, vote embedding and finalize.

The suite runs without a database, pytex, MinIO or Redis. `session.get` reads from a
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
from app.modules.pdf.pytex_client import PytexError
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import ProtocolService, protocol_storage_key
from app.settings import get_settings
from app.shared.errors import ConflictError, NotFoundError, ServiceUnavailableError
from tests._support.pdf_fakes import FakePytex
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
    return SimpleNamespace(id=GID, slug="stupa", cd_variant=cd_variant)


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
            "allowChange": True,
            "tieBreak": "rejected",
            "abstainCountsQuorum": True,
            "quorum": None,
        },
        "eligible_count": 10,
        "opens_at": None,
        "closes_at": None,
        "status": "closed",
        "result": "passed",
    }
    base.update(over)
    return SimpleNamespace(**base)


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
    created = _protocol(markdown="", status="draft")
    session = FakeSession(
        store={MID: _real_meeting(), GID: _real_gremium()},
        # execute order: _by_meeting is empty, pg_insert is ignored, _by_meeting is new
        results=[result(), result(), result(created)],
    )
    out = await _service(session).get_or_create(MID, author="p1")
    assert out.status == "draft"
    assert out.markdown == ""
    assert session.committed == 1


async def test_get_or_create_returns_existing_idempotent() -> None:
    existing = _protocol(markdown="# schon da")
    session = FakeSession(results=[result(existing)])
    out = await _service(session).get_or_create(MID)
    assert out.markdown == "# schon da"
    assert session.committed == 0  # a pure read, no insert and no commit


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
    """Defensive: a row that vanishes before the re-select gives 404, not a None deref."""
    session = FakeSession(
        store={MID: _real_meeting(), GID: _real_gremium()},
        results=[result(), result(), result()],  # nothing existing, insert, empty re-select
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
    session = FakeSession(results=[result()])  # _get finds nothing
    with pytest.raises(NotFoundError):
        await _service(session).update_markdown(PID, "# Neu")


async def test_embed_votes_appends_snippet_and_ref() -> None:
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(
        store={VID: _vote()},
        results=[
            result(proto),  # _get
            result(),  # existing refs (none)
            result(uuid4()),  # pg_insert ProtocolVoteRef returns the inserted id
            result(_vote()),  # VotingService._get_vote
            result("yes", "yes", "no"),  # VotingService._aggregate
        ],
    )
    out = await _service(session).embed_votes(PID, [VID])
    assert "> [!abstimmung]" in out.markdown
    assert "Ergebnis" not in out.markdown  # dropped: the tally box carries the result
    assert "yes: 2, no: 1" in out.markdown
    assert session.committed == 1


async def test_embed_votes_idempotent_skips_referenced() -> None:
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(
        results=[result(proto), result(VID)]  # VID is already referenced (pre-query)
    )
    out = await _service(session).embed_votes(PID, [VID])
    assert out.markdown == "# TOP 1"  # unchanged


async def test_embed_votes_concurrent_ref_skips_snippet() -> None:
    """A parallel insert wins: ON CONFLICT returns nothing, so no snippet doubles."""
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(
        store={VID: _vote()},
        results=[
            result(proto),  # _get
            result(),  # existing refs (none, pre-query)
            result(),  # pg_insert returns nothing: a parallel insert won the conflict
        ],
    )
    out = await _service(session).embed_votes(PID, [VID])
    assert out.markdown == "# TOP 1"  # unchanged


async def test_embed_votes_unknown_vote_404() -> None:
    session = FakeSession(store={}, results=[result(_protocol()), result()])
    with pytest.raises(NotFoundError):
        await _service(session).embed_votes(PID, [VID])


async def test_embed_votes_on_final_conflict() -> None:
    session = FakeSession(results=[result(_protocol(status="final"))])
    with pytest.raises(ConflictError):
        await _service(session).embed_votes(PID, [VID])


async def test_finalize_renders_stores_and_mails() -> None:
    proto = _protocol()
    storage = FakeStorage()
    pytex = FakePytex(pdf=b"%PDF-1.4 ok")
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium("stupa")},
        # The first empty result is the empty agenda. Then come the members, which are
        # the base of the union, and an empty mail list.
        results=[result(proto), result(), result("a@x.de", "b@x.de"), result()],
    )
    out = await _service(
        session, storage=storage, pytex=pytex, mail_queue=mail
    ).finalize(PID, now=NOW)

    assert out.status == "final"
    assert out.sent_at == NOW
    assert proto.pdf_storage_key == protocol_storage_key(PID)
    assert storage.puts and storage.puts[0][2] == "application/pdf"
    assert pytex.calls and pytex.calls[0][1] == "protocol-stupa"
    assert out.pdf_url is not None
    assert len(mail.sent) == 1
    assert mail.sent[0].to == ("a@x.de", "b@x.de")
    # The PDF travels as an attachment (#protocol-mail-pdf). The earlier link needed a
    # login plus meeting.manage and was worthless for the recipients.
    assert [a.filename for a in mail.sent[0].attachments] == ["protokoll.pdf"]
    assert mail.sent[0].attachments[0].content.startswith(b"%PDF")


async def test_finalize_renders_user_markdown_trusted() -> None:
    """The sanitizer gives the RCE protection, not the trust level.

    `sanitize_user_markdown` removes the `eval` escape unconditionally. The protocol
    body therefore renders as `trusted`. That is the client default, because the call
    passes no override and `trust_level` stays None. The protocol variant needs the
    pytex template machinery, which `untrusted` refuses with a 400.
    """
    proto = _protocol()
    pytex = FakePytex(pdf=b"%PDF")
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium("stupa")},
        results=[result(proto), result(), result(), result()],
    )
    await _service(session, storage=FakeStorage(), pytex=pytex).finalize(PID, now=NOW)
    assert pytex.trust_levels == [None]


async def test_finalize_uploads_and_mails_only_after_commit() -> None:
    """#pre-commit-side-effects: the storage put and the mail enqueue run after the commit.

    The fakes count the commit and record the put and the enqueue only after it. The
    test checks the committed end state. The PDF is in the storage, the mail is queued
    and the commit ran.
    """
    proto = _protocol()
    storage = FakeStorage()
    pytex = FakePytex(pdf=b"%PDF-1.4 ok")
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium("stupa")},
        results=[result(proto), result(), result("a@x.de"), result()],
    )
    await _service(
        session, storage=storage, pytex=pytex, mail_queue=mail
    ).finalize(PID, now=NOW)
    assert session.committed == 1
    # Exactly one put (single render) and one mail, both from the post-commit path.
    assert [p[0] for p in storage.puts] == [protocol_storage_key(PID)]
    assert len(mail.sent) == 1


async def test_finalize_storage_error_after_commit_raises_503() -> None:
    """A transient failure of the post-commit storage `put` gives a 503.

    The protocol is already committed as `final`, so a retry is an idempotent no-op.
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
            session, storage=_BoomStorage(), pytex=FakePytex()
        ).finalize(PID, now=NOW)
    assert session.committed == 1  # the commit ran before the storage put
    assert proto.status == "final"


async def test_finalize_without_storage_degrades_but_mails() -> None:
    proto = _protocol()
    pytex = FakePytex()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result(), result("a@x.de"), result()],
    )
    out = await _service(session, storage=None, pytex=pytex, mail_queue=mail).finalize(
        PID, now=NOW
    )
    assert out.status == "final"
    assert out.pdf_url is None
    assert proto.pdf_storage_key is None
    assert pytex.calls == []  # render skipped, no storage
    assert len(mail.sent) == 1 and mail.sent[0].attachments == ()  # no PDF, no storage


async def test_finalize_idempotent_when_already_final() -> None:
    proto = _protocol(status="final", pdf_storage_key="pdf/protocol/x.pdf")
    storage = FakeStorage()
    pytex = FakePytex()
    mail = FakeMailQueue()
    session = FakeSession(results=[result(proto)])
    out = await _service(
        session, storage=storage, pytex=pytex, mail_queue=mail
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert out.pdf_url is not None  # freshly signed from the existing key
    assert storage.puts == [] and pytex.calls == [] and mail.sent == []


async def test_finalize_pytex_error_raises_503() -> None:
    proto = _protocol()
    pytex = FakePytex(error=PytexError("boom", retryable=True))
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()}, results=[result(proto)]
    )
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage=FakeStorage(), pytex=pytex).finalize(
            PID, now=NOW
        )
    assert proto.status == "draft"  # the draft stays


async def test_finalize_no_recipients_skips_mail() -> None:
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result()],  # empty mail list
    )
    out = await _service(
        session, storage=FakeStorage(), pytex=FakePytex(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert mail.sent == []


async def test_finalize_members_receive_even_without_maillist() -> None:
    """An empty mail_list still sends to the active Gremium members.

    #protocol-recipients: the members are always the base of the recipient union.
    """
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),  # _get
            result(),  # _assemble_from_agenda (no agenda items)
            result("a@x.de", "b@x.de"),  # members (scalars)
            result(),  # _recipients: empty mail list
        ],
    )
    out = await _service(
        session, storage=FakeStorage(), pytex=FakePytex(), mail_queue=mail
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
        session, storage=FakeStorage(), pytex=FakePytex(), mail_queue=None
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
        session, storage=FakeStorage(), pytex=FakePytex(), mail_queue=mail
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


async def test_start_finalize_marks_rendering_and_requests_enqueue() -> None:
    proto = _protocol()
    session = FakeSession(results=[result(proto)])
    out, needs_render = await _service(session).start_finalize(PID)
    assert needs_render is True
    assert out.status == "rendering" and proto.status == "rendering"
    assert session.committed == 1  # the status flip commits before the enqueue


async def test_start_finalize_idempotent_while_rendering() -> None:
    proto = _protocol(status="rendering")
    session = FakeSession(results=[result(proto)])
    out, needs_render = await _service(session).start_finalize(PID)
    assert needs_render is False
    assert out.status == "rendering"
    assert session.committed == 0  # no double enqueue and no write


async def test_start_finalize_idempotent_when_final() -> None:
    proto = _protocol(status="final", pdf_storage_key=protocol_storage_key(PID))
    session = FakeSession(results=[result(proto)])
    out, needs_render = await _service(session).start_finalize(PID)
    assert needs_render is False
    assert out.status == "final"


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
        session, storage=FakeStorage(), pytex=FakePytex(), mail_queue=FakeMailQueue()
    ).finalize(PID, now=NOW)
    assert out.status == "final"


async def test_finalize_recipients_union_members_plus_maillist() -> None:
    """#protocol-recipients: an extra mail list extends the member list.

    The result is a deduplicated union. The extra list never replaces the members.
    """
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),  # _get
            result(),  # _assemble_from_agenda (no agenda items)
            result("member@x.de"),  # active members
            result(["extra@y.de", "member@x.de"]),  # extra mail list, with a duplicate
        ],
    )
    await _service(
        session, storage=FakeStorage(), pytex=FakePytex(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert len(mail.sent) == 1
    assert mail.sent[0].to == ("member@x.de", "extra@y.de")


async def test_get_by_meeting_reads_without_create() -> None:
    """Reload and poll path (#429): reads the existing protocol and never creates one."""
    proto = _protocol(status="rendering")
    session = FakeSession(results=[result(proto)])
    out = await _service(session).get_by_meeting(MID)
    assert out.status == "rendering"
    assert session.added == [] and session.committed == 0


async def test_get_by_meeting_404_without_protocol() -> None:
    session = FakeSession(results=[result()])
    with pytest.raises(NotFoundError):
        await _service(session).get_by_meeting(MID)
