"""Extra branch and line coverage for the protocol, pdf and files services.

The suite adds the paths that `test_protocol_service` and `test_files_service` do not
reach. It covers the protocol dual-render assembly from the agenda (#PII-Re-Add) and the
public PDF variant, plus `_quorate`, `_header_meta` and `_local_end_time`. Finally it
covers the `FilesService` operations `list_for_application`, `delete` and
`delete_for_application`.

The suite runs without a database, typst, MinIO or Redis. The sessions are fakes with
a store and ordered result queues. The storage, typst and mail fakes come from
`tests._support`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from datetime import time as _time
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.modules.applications.models import Application
from app.modules.files import service as files_service
from app.modules.files.models import Attachment
from app.modules.pdf.typst_client import TypstError
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import (
    ProtocolService,
    protocol_public_storage_key,
    protocol_storage_key,
)
from app.settings import get_settings, load_settings
from app.shared.errors import (
    BadRequestError,
    NotFoundError,
    ServiceUnavailableError,
)
from tests._support.files_fakes import FailingStorage, FakeScanQueue, FakeStorage
from tests._support.notifications_fakes import FakeSession as NotifSession
from tests._support.pdf_fakes import FakeTypst
from tests._support.protocol_fakes import (
    FakeMailQueue,
    FakeSession,
    result,
)
from tests._support.protocol_fakes import FakeStorage as ProtoStorage

SETTINGS = load_settings()
NOW = datetime(2026, 6, 12, 19, 0, tzinfo=UTC)
PID = uuid4()
MID = uuid4()
GID = uuid4()


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


def _meeting(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": MID,
        "gremium_id": GID,
        "title": "StuPa-Sitzung",
        "date": date(2026, 6, 12),
        "start_time": _time(18, 0),
        "closed_at": None,
        "protokollant_id": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _gremium(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": GID,
        "name": "StuPa",
        "slug": "stupa",
        "quorum_percent": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _agenda_item(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "meeting_id": MID,
        "title": "TOP A",
        "body": "Diskussion zum Thema.",
        "position": 1,
        "non_public": False,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _vote_row(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "application_id": None,
        "meeting_id": MID,
        "agenda_item_id": None,
        "question": "Beschlussfrage?",
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


def _service(session: Any, **infra: Any) -> ProtocolService:
    return ProtocolService(session, settings=get_settings(), **infra)


def test_public_storage_key_has_public_suffix() -> None:
    assert protocol_public_storage_key(PID) == f"pdf/protocol/{PID}-public.pdf"


async def test_public_pdf_url_present_when_key_and_storage() -> None:
    proto = _protocol(public_pdf_storage_key=protocol_public_storage_key(PID))
    session = FakeSession(results=[result(proto)])
    out = await _service(session, storage=ProtoStorage()).update_markdown(PID, "x")
    assert out.public_pdf_url == f"/api/protocols/{PID}/pdf/public"


async def test_public_pdf_url_none_without_storage() -> None:
    proto = _protocol(public_pdf_storage_key=protocol_public_storage_key(PID))
    session = FakeSession(results=[result(proto)])
    out = await _service(session, storage=None).update_markdown(PID, "x")
    assert out.public_pdf_url is None


async def test_public_pdf_url_none_without_key() -> None:
    proto = _protocol(public_pdf_storage_key=None)
    session = FakeSession(results=[result(proto)])
    out = await _service(session, storage=ProtoStorage()).update_markdown(PID, "x")
    assert out.public_pdf_url is None


async def test_get_public_pdf_bytes_streams() -> None:
    key = protocol_public_storage_key(PID)
    proto = _protocol(public_pdf_storage_key=key)
    storage = ProtoStorage()
    storage.blobs[key] = b"%PDF public"
    session = FakeSession(results=[result(proto)])
    data = await _service(session, storage=storage).get_public_pdf_bytes(PID)
    assert data == b"%PDF public"


async def test_get_public_pdf_bytes_404_without_key() -> None:
    proto = _protocol(public_pdf_storage_key=None)
    session = FakeSession(results=[result(proto)])
    with pytest.raises(NotFoundError):
        await _service(session, storage=ProtoStorage()).get_public_pdf_bytes(PID)


async def test_get_public_pdf_bytes_404_without_storage() -> None:
    proto = _protocol(public_pdf_storage_key=protocol_public_storage_key(PID))
    session = FakeSession(results=[result(proto)])
    with pytest.raises(NotFoundError):
        await _service(session, storage=None).get_public_pdf_bytes(PID)


async def test_get_public_pdf_bytes_storage_error_503() -> None:
    key = protocol_public_storage_key(PID)
    proto = _protocol(public_pdf_storage_key=key)
    session = FakeSession(results=[result(proto)])
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage=FailingStorage()).get_public_pdf_bytes(PID)


async def test_get_pdf_bytes_storage_error_503() -> None:
    """A transient storage error on the internal PDF stream gives a 503."""
    key = protocol_storage_key(PID)
    proto = _protocol(pdf_storage_key=key)
    session = FakeSession(results=[result(proto)])
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage=FailingStorage()).get_pdf_bytes(PID)


async def test_finalize_dual_render_with_non_public_top() -> None:
    """At least one non-public agenda item forces an internal and a public PDF.

    The mail carries only the public variant.

    ``_has_non_public`` reads ``session.scalar``, where 1 is truthy. Each
    ``_build_document`` call, internal and public, then runs ``_assemble_from_agenda``
    for the items, ``_header_meta`` for the protokollant scalar (the attendance query
    short-circuits), and ``_quorate`` for the member count. A member count of 0 gives no
    quorum statement. The mail carries the public PDF as the attachment.

    The fake session serves, in order:

    - execute: ``_get``, the internal items (empty), the public items (empty), the members of
      ``_recipients`` and its mail list;
    - scalar: ``_has_non_public`` (1), the internal protokollant, the internal member count,
      the public protokollant, the public member count, the gremium name for ``_send``.
    """
    proto = _protocol()
    storage = ProtoStorage()
    typst = FakeTypst(pdf=b"%PDF dual")
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),
            result(),
            result(),
            result("m@x.de"),
            result(),
        ],
    )
    session.scalar_results = [
        1,
        None,
        0,
        None,
        0,
        "StuPa",
    ]
    out = await _service(
        session, storage=storage, typst=typst, mail_queue=mail
    ).finalize(PID, now=NOW)

    assert out.status == "final"
    assert proto.pdf_storage_key == protocol_storage_key(PID)
    assert proto.public_pdf_storage_key == protocol_public_storage_key(PID)
    assert len(typst.calls) == 2
    keys = {k for k, _len, _ct in storage.puts}
    assert keys == {protocol_storage_key(PID), protocol_public_storage_key(PID)}
    assert len(mail.sent) == 1
    assert [a.filename for a in mail.sent[0].attachments] == ["protokoll.pdf"]


async def test_finalize_dual_render_without_storage_skips_uploads() -> None:
    """The dual-render path without storage (DEV or demo) uploads nothing.

    `_render_pdf` returns None, so there is no upload and no PDF attachment. The test
    covers the `is None` branches of the dual-render block.

    The fake session serves the same queue as the dual render with a non-public TOP:
    ``_has_non_public`` is true, so both variants render.
    """
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),
            result(),
            result(),
            result("m@x.de"),
            result(),
        ],
    )
    session.scalar_results = [
        1,
        None,
        0,
        None,
        0,
        "StuPa",
    ]
    out = await _service(
        session, storage=None, typst=FakeTypst(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert proto.pdf_storage_key is None and proto.public_pdf_storage_key is None
    assert len(mail.sent) == 1 and mail.sent[0].attachments == ()


async def test_assemble_from_agenda_builds_blocks_with_votes() -> None:
    """Existing agenda items build the protocol from the bodies and the vote snippets.

    An empty item gets the fallback title "Tagesordnungspunkt".

    The fake session serves, in order:

    - execute: ``_get``, the items, the votes of the first item, ``voting._get_vote``, the
      ballots for ``voting._aggregate``, the votes of the second item (empty), the members
      and the mail list of ``_recipients`` (empty);
    - scalar: ``has_non_public`` (0), the protokollant, the member count.
    """
    proto = _protocol(markdown="# Fallback (sollte ignoriert werden)")
    item_with_vote = _agenda_item(title="Haushalt", body="Body Haushalt", position=1)
    item_empty = _agenda_item(
        title=None, body=None, position=2, non_public=False
    )
    vote = _vote_row(agenda_item_id=item_with_vote.id, question="Genehmigen?")
    storage = ProtoStorage()
    typst = FakeTypst(pdf=b"%PDF asm")
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium(), vote.id: vote},
        results=[
            result(proto),
            result(item_with_vote, item_empty),
            result(vote),
            result(vote),
            result("yes", "yes", "no"),
            result(),
            result(),
            result(),
        ],
    )
    session.scalar_results = [0, None, 0]
    out = await _service(
        session, storage=storage, typst=typst, mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    rendered_md = typst.calls[0][0]
    assert "# Haushalt" in rendered_md
    assert "Body Haushalt" in rendered_md
    assert "# Tagesordnungspunkt" in rendered_md
    assert "[!abstimmung]" in rendered_md


async def test_assemble_public_redacts_non_public_top() -> None:
    """`public=True` replaces the body and the snippets of non-public agenda items.

    A placeholder takes their place. The heading stays, so the numbering stays stable.

    A non-public title can encode the subject. The internal variant keeps it. The public
    variant replaces it with a neutral heading. The single top-level `#` keeps the
    numbering stable.

    The fake session serves ``_get``, the internal items with the votes of both items,
    the public items with the votes of the public item only (the non-public item is
    skipped), then the members and the mail list.
    """
    proto = _protocol()
    np_item = _agenda_item(title="Personalie", body="Geheim", non_public=True)
    pub_item = _agenda_item(title="Offenes", body="Sichtbar", non_public=False)
    storage = ProtoStorage()
    typst = FakeTypst(pdf=b"%PDF red")
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),
            result(np_item, pub_item),
            result(),
            result(),
            result(np_item, pub_item),
            result(),
            result(),
            result(),
        ],
    )
    session.scalar_results = [1, None, 0, None, 0, "StuPa"]
    await _service(
        session, storage=storage, typst=typst, mail_queue=None
    ).finalize(PID, now=NOW)
    internal_md = typst.calls[0][0]
    public_md = typst.calls[1][0]
    assert "Geheim" in internal_md
    assert "Geheim" not in public_md
    assert "nicht-öffentlicher Tagesordnungspunkt" in public_md
    assert "# Personalie" in internal_md
    assert "# Personalie" not in public_md
    assert "# Nicht-öffentlicher Tagesordnungspunkt" in public_md


async def test_assemble_skips_cancelled_votes_in_query() -> None:
    """A cancelled vote gives no snippet.

    The SELECT filters it out. An empty result covers the branch.

    The fake session serves the items, no votes (all cancelled), the members and the
    mail list.
    """
    proto = _protocol()
    item = _agenda_item(title="X", body=None)
    storage = ProtoStorage()
    typst = FakeTypst()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),
            result(item),
            result(),
            result(),
            result(),
        ],
    )
    session.scalar_results = [0, None, 0]
    out = await _service(
        session, storage=storage, typst=typst, mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert "[!abstimmung]" not in typst.calls[0][0]


async def test_quorate_with_explicit_percent_threshold() -> None:
    """A set gremium.quorum_percent gives the threshold present*100 >= percent*members.

    10 members, 5 present: 50% of 10 is 5, so 500 >= 500 is true.
    """
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [10]
    gremium = _gremium(quorum_percent=50)
    assert await svc._quorate(gremium, None, present_count=5) is True


async def test_quorate_percent_not_met() -> None:
    """10 members, 5 present: 60% of 10 is 6, so 500 >= 600 is false."""
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [10]
    gremium = _gremium(quorum_percent=60)
    assert await svc._quorate(gremium, None, present_count=5) is False


async def test_quorate_default_majority_rule() -> None:
    """Without quorum_percent the rule is more than half (present*2 > members)."""
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [10]
    gremium = _gremium(quorum_percent=None)
    assert await svc._quorate(gremium, None, present_count=6) is True
    session.scalar_results = [10]
    assert await svc._quorate(gremium, None, present_count=5) is False


async def test_quorate_none_without_gremium() -> None:
    svc = _service(FakeSession())
    assert await svc._quorate(None, None, present_count=3) is None


async def test_quorate_none_without_members() -> None:
    """A gremium without members gives no quorum statement."""
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [0]
    assert await svc._quorate(_gremium(), None, present_count=3) is None


async def test_quorate_none_when_member_count_query_returns_none() -> None:
    """`session.scalar` returns None, so `or 0` makes members 0 and the result None.

    An empty ``scalar_results`` makes ``scalar()`` return None, so the ``or 0`` applies.
    """
    svc = _service(FakeSession())
    assert await svc._quorate(_gremium(), None, present_count=3) is None


async def test_header_meta_returns_empty_without_meeting() -> None:
    svc = _service(FakeSession())
    header = await svc._header_meta(None)
    assert header.protokollant is None and header.present == [] and header.absent == []
    assert header.excused == [] and header.keepers == []
    assert header.present_count == 0 and header.datalines == []


async def test_header_meta_resolves_protokollant_name() -> None:
    """Without keeper periods, protokollant_id resolves the name through `session.scalar`.

    The guest count comes first (no guests). The FakeSession short-circuits the
    attendance query, so the attendance stays empty.
    """
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [0, "Frau Schmidt"]
    meeting = _meeting(protokollant_id=uuid4())
    header = await svc._header_meta(cast("Any", meeting))
    assert header.protokollant == "Frau Schmidt"
    assert header.keepers == []
    assert header.present == [] and header.absent == [] and header.present_count == 0
    assert header.datalines == []


async def test_header_meta_public_redacts_names_keeps_counts() -> None:
    """`public=True` drops the protokollant and the name lists.

    Only the counters stay, as data lines. The true `present_count` stays correct.

    The guest count comes first (no guests). The fake attendance is empty, so all
    counters are 0.
    """
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [0, "Frau Schmidt"]
    meeting = _meeting(protokollant_id=uuid4())
    header = await svc._header_meta(cast("Any", meeting), public=True)
    assert header.protokollant is None and header.keepers == []
    assert header.present == [] and header.absent == [] and header.excused == []
    assert header.present_count == 0
    assert header.datalines == ["Anwesend: 0", "Entschuldigt: 0", "Abwesend: 0"]


def test_local_end_time_none_when_not_datetime() -> None:
    svc = _service(FakeSession())
    assert svc._local_end_time(None) is None
    assert svc._local_end_time("not-a-datetime") is None


def test_local_end_time_converts_utc_to_local() -> None:
    """17:30:45 UTC is 19:30 in Berlin summer time, with seconds and microseconds zeroed."""
    svc = _service(FakeSession())
    closed = datetime(2026, 6, 12, 17, 30, 45, tzinfo=UTC)
    end = svc._local_end_time(closed)
    assert isinstance(end, _time)
    assert end == _time(19, 30)


async def test_finalize_uses_meeting_closed_at_end_time() -> None:
    """The full finalize path with a set closed_at activates `_local_end_time`."""
    proto = _protocol()
    meeting = _meeting(closed_at=datetime(2026, 6, 12, 17, 30, tzinfo=UTC))
    storage = ProtoStorage()
    typst = FakeTypst()
    session = FakeSession(
        store={MID: meeting, GID: _gremium()},
        results=[result(proto), result(), result(), result()],
    )
    session.scalar_results = [0, None, 0]
    out = await _service(
        session, storage=storage, typst=typst, mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"


async def test_finalize_non_retryable_render_error_400() -> None:
    proto = _protocol()
    typst = FakeTypst(error=TypstError("bad markup", retryable=False))
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result()],
    )
    session.scalar_results = [0, None, 0]
    with pytest.raises(BadRequestError) as exc:
        await _service(session, storage=ProtoStorage(), typst=typst).finalize(
            PID, now=NOW
        )
    assert exc.value.code == "render_failed"


async def test_finalize_storage_error_during_render_503() -> None:
    """A failed storage put gives a 503."""
    proto = _protocol()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result()],
    )
    session.scalar_results = [0, None, 0]
    with pytest.raises(ServiceUnavailableError):
        await _service(
            session, storage=FailingStorage(), typst=FakeTypst()
        ).finalize(PID, now=NOW)


async def test_send_subject_and_body_include_gremium_and_date() -> None:
    """The subject and the body carry the Gremium, the meeting and the date.

    The body names the PDF attachment ("liegt als PDF bei"). The fake session serves the
    items (empty), the members and the mail list. The scalars are the guest count,
    ``has_non_public`` (false), the member count and the gremium name for ``_send``.
    ``_meeting`` sets protokollant_id to None, so no protokollant scalar is read.
    """
    proto = _protocol()
    meeting = _meeting()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: meeting, GID: _gremium()},
        results=[
            result(proto),
            result(),
            result("a@x.de"),
            result(),
        ],
    )
    session.scalar_results = [0, 0, 5, "StuPa"]
    await _service(
        session, storage=ProtoStorage(), typst=FakeTypst(), mail_queue=mail
    ).finalize(PID, now=NOW)
    msg = mail.sent[0]
    assert "StuPa" in msg.subject
    assert "12.06.2026" in msg.subject
    assert "Sitzung: StuPa-Sitzung" in msg.text
    assert "Gremium: StuPa" in msg.text
    assert "Datum: 12.06.2026" in msg.text
    assert "liegt als PDF bei" in msg.text


async def test_send_without_gremium_name_and_meeting() -> None:
    """No Gremium name and no meeting give a lean subject and body without a PDF hint.

    The store holds no meeting, so the meeting is None, the body is the empty Markdown
    fallback, and no protokollant scalar is read. The scalars are ``has_non_public``
    (0), the member count and a gremium name of None. Without storage there is no PDF,
    so the intro drops the hint and no file travels. The subject names neither Gremium
    nor date.
    """
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={GID: _gremium(name=None)},
        results=[
            result(proto),
            result(),
            result("a@x.de"),
            result(),
        ],
    )
    session.scalar_results = [0, 5, None]
    await _service(
        session, storage=None, typst=FakeTypst(), mail_queue=mail
    ).finalize(PID, now=NOW)
    msg = mail.sent[0]
    assert msg.subject == "Sitzungsprotokoll"
    assert "liegt als PDF bei" not in msg.text
    assert msg.attachments == ()


async def test_embed_vote_title_for_application_reference() -> None:
    """A set application_id makes the snippet title reference the application.

    With question None, ``build_vote_snippet`` uses the application reference of
    ``_vote_title``. The fake session serves ``_get``, no existing refs, the id of the
    ``pg_insert`` RETURNING, ``voting._get_vote`` and the ballots for
    ``voting._aggregate``.
    """
    app_id = uuid4()
    vid = uuid4()
    proto = _protocol(markdown="# TOP 1")
    vote = _vote_row(id=vid, application_id=app_id, question=None)
    session = FakeSession(
        store={vid: vote},
        results=[
            result(proto),
            result(),
            result(uuid4()),
            result(vote),
            result("yes", "no"),
        ],
    )
    out = await _service(session).embed_votes(PID, [vid])
    assert f"Antrag {str(app_id)[:8]}" in out.markdown


def test_vote_title_generic_question_fallbacks() -> None:
    from app.modules.protocol.service import _vote_title

    assert _vote_title(None, "Frage?") == "Frage?"
    assert _vote_title(None, "   ") == "Beschlussfrage"
    assert _vote_title(None, None) == "Beschlussfrage"


async def test_build_document_fallback_title_without_meeting() -> None:
    """Without agenda items the build falls back to ``protocol.markdown``.

    The store holds no meeting and no gremium, so both resolve to None.
    ``has_non_public`` is false.
    """
    proto = _protocol(markdown="# Bestehendes Markdown")
    typst = FakeTypst()
    session = FakeSession(
        store={},
        results=[result(proto), result(), result(), result()],
    )
    session.scalar_results = [0]
    out = await _service(
        session, storage=ProtoStorage(), typst=typst, mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert "# Bestehendes Markdown" in typst.calls[0][0]


@pytest.fixture(autouse=True)
def _mock_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the sniff and validate step to accept a PDF, so libmagic is not needed."""
    monkeypatch.setattr(
        files_service, "validate_upload", lambda filename, data: "application/pdf"
    )


class _FilesSession(NotifSession):
    """NotifSession plus the `delete` and `flush` that the delete path needs."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.deleted: list[Any] = []
        self.flushed = 0

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)
        self.store.pop(cast("uuid.UUID", getattr(obj, "id", None)), None)

    async def flush(self) -> None:
        self.flushed += 1


def _files_service(
    session: NotifSession,
    *,
    storage: object | None = None,
    queue: object | None = None,
) -> files_service.FilesService:
    return files_service.FilesService(
        session, storage=storage, queue=queue, settings=SETTINGS  # type: ignore[arg-type]
    )


def _attachment(session: NotifSession, **kw: object) -> Attachment:
    att = Attachment(
        application_id=uuid.uuid4(),
        filename="doc.pdf",
        mime="application/pdf",
        size=10,
        storage_key="k/doc.pdf",
        scanned=False,
        scan_result=None,
    )
    att.id = uuid.uuid4()
    for key, value in kw.items():
        setattr(att, key, value)
    session.add(att)
    return att


async def test_list_for_application_returns_outs() -> None:
    """list_for_application maps the rows to AttachmentOut."""
    session = NotifSession()
    a1 = Attachment(
        application_id=uuid.uuid4(), filename="a.pdf", mime="application/pdf",
        size=1, storage_key="k1", scanned=True, scan_result=SETTINGS and "clean",
    )
    a1.id = uuid.uuid4()
    a2 = Attachment(
        application_id=uuid.uuid4(), filename="b.pdf", mime="application/pdf",
        size=2, storage_key="k2", scanned=False, scan_result=None,
    )
    a2.id = uuid.uuid4()
    session._scalars = [[a1, a2]]
    out = await _files_service(session, storage=FakeStorage()).list_for_application(
        uuid.uuid4()
    )
    assert [o.filename for o in out] == ["a.pdf", "b.pdf"]
    assert out[1].scanned is False


async def test_list_for_application_empty() -> None:
    session = NotifSession()
    session._scalars = [[]]
    out = await _files_service(session).list_for_application(uuid.uuid4())
    assert out == []


async def test_delete_removes_row_storage_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delete call removes the DB row and the storage object, audits, then commits."""
    calls: list[dict[str, object]] = []

    async def _record(session: object, **kw: object) -> None:
        calls.append(kw)

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = _FilesSession()
    att = _attachment(session)
    storage = FakeStorage()
    storage.objects["k/doc.pdf"] = (b"x", "application/pdf")
    svc = _files_service(session, storage=storage)
    await svc.delete(att.id, actor="admin")
    assert att in session.deleted
    assert storage.removed == ["k/doc.pdf"]
    assert session.committed == 1
    assert calls and calls[0]["target_type"] == "attachment"
    assert calls[0]["actor"] == "admin"


async def test_delete_tolerates_storage_remove_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delete call swallows a storage remove error as a best effort.

    The delete must NOT raise.
    """
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = _FilesSession()
    att = _attachment(session)
    svc = _files_service(session, storage=FailingStorage())
    await svc.delete(att.id, actor="admin")
    assert session.committed == 1


async def test_delete_without_storage_or_key_skips_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delete call tries no remove without a storage or without a storage_key.

    Case 1 has no storage. Case 2 has a storage, but storage_key is None.
    """
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = _FilesSession()
    att = _attachment(session)
    await _files_service(session, storage=None).delete(att.id, actor="a")
    assert session.committed == 1
    session2 = _FilesSession()
    att2 = _attachment(session2, storage_key=None)
    storage = FakeStorage()
    await _files_service(session2, storage=storage).delete(att2.id, actor="a")
    assert storage.removed == []


async def test_delete_unknown_attachment_404() -> None:
    session = NotifSession()
    with pytest.raises(NotFoundError):
        await _files_service(session, storage=FakeStorage()).delete(
            uuid.uuid4(), actor="a"
        )


async def test_delete_for_application_removes_all_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_for_application removes every row and object, audits, and never commits.

    Only the attachment with a storage key is removed from storage. Each attachment gets
    an audit entry, and the method does NOT commit on its own.
    """
    calls: list[dict[str, object]] = []

    async def _record(session: object, **kw: object) -> None:
        calls.append(kw)

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = _FilesSession()
    a1 = _attachment(session, storage_key="k/1")
    a2 = _attachment(session, storage_key=None)
    session._scalars = [[a1, a2]]
    storage = FakeStorage()
    storage.objects["k/1"] = (b"x", "application/pdf")
    n = await _files_service(session, storage=storage).delete_for_application(
        uuid.uuid4(), actor="dsgvo"
    )
    assert n == 2
    assert storage.removed == ["k/1"]
    assert len(calls) == 2
    assert session.committed == 0


async def test_delete_for_application_tolerates_remove_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_for_application swallows a storage remove error."""
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = _FilesSession()
    a1 = _attachment(session, storage_key="k/1")
    session._scalars = [[a1]]
    n = await _files_service(
        session, storage=FailingStorage()
    ).delete_for_application(uuid.uuid4(), actor="dsgvo")
    assert n == 1


async def test_delete_for_application_empty_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = NotifSession()
    session._scalars = [[]]
    n = await _files_service(session, storage=FakeStorage()).delete_for_application(
        uuid.uuid4(), actor="dsgvo"
    )
    assert n == 0


def test_max_bytes_clamps_to_model_cap() -> None:
    from app.modules.files.models import MAX_ATTACHMENT_BYTES

    svc = _files_service(NotifSession(), storage=FakeStorage())
    assert svc.max_bytes == min(SETTINGS.attachment_max_bytes, MAX_ATTACHMENT_BYTES)


async def test_upload_with_field_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upload with field_key sets it on the row.

    The upload writes an audit entry, which ``NotifSession`` cannot chain, so the test
    captures it. The audit records only that a field key exists, never the client text.
    """
    audits: list[dict[str, object]] = []

    async def _record(session: object, **kw: object) -> None:
        audits.append(kw)

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = NotifSession()
    app = Application()
    app.id = uuid.uuid4()
    session.add(app)
    storage, queue = FakeStorage(), FakeScanQueue()
    out = await _files_service(session, storage=storage, queue=queue).upload(
        app.id,
        filename="offer.pdf",
        data=b"%PDF-1.4 fake",
        by="p",
        field_key="kostenaufstellung",
    )
    assert out.filename == "offer.pdf"
    added = [a for a in session.added if isinstance(a, Attachment)]
    assert added and added[0].field_key == "kostenaufstellung"
    assert len(queue.enqueued) == 1
    assert audits[0]["data"]["hasFieldKey"] is True  # type: ignore[index]
    assert "fieldKey" not in audits[0]["data"]  # type: ignore[operator]
    assert "isComparisonOffer" not in audits[0]["data"]  # type: ignore[operator]
