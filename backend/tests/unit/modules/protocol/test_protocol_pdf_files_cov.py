"""Extra branch and line coverage for the protocol, pdf and files services.

The suite adds the paths that `test_protocol_service`, `test_pdf_service` and
`test_files_service` do not reach. It covers the protocol dual-render assembly from
the agenda (#PII-Re-Add) and the public PDF variant. It also covers `_quorate`,
`_header_meta` and `_local_end_time`. It drives the `PdfService` document load path
`load_application_doc` with its joins. Finally it covers the `FilesService` operations
`list_for_application`, `delete` and `delete_for_application`.

The suite runs without a database, pytex, MinIO or Redis. The sessions are fakes with
a store and ordered result queues. The storage, pytex and mail fakes come from
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
from app.modules.pdf.pytex_client import PytexError
from app.modules.pdf.service import PdfService
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
from tests._support.pdf_fakes import FakePytex
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


# ProtocolService helpers and fakes.
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
        "cd_variant": "stupa",
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
    """
    proto = _protocol()
    storage = ProtoStorage()
    pytex = FakePytex(pdf=b"%PDF dual")
    mail = FakeMailQueue()
    # _has_non_public reads session.scalar, where 1 is truthy.
    # Each _build_document call, internal and public, then runs in this order:
    #   _assemble_from_agenda for the items, _header_meta for the protokollant scalar
    #   and the attendance short circuit, _quorate for the member count.
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),  # _get
            result(),       # internal: _assemble_from_agenda items (empty)
            result(),       # public: _assemble_from_agenda items (empty)
            result("m@x.de"),  # _recipients resolves the members (scalars)
            result(),       # _recipients mail list (execute)
        ],
    )
    session.scalar_results = [
        1,        # _has_non_public is true
        None,     # _header_meta protokollant, internal
        0,        # _quorate member count, internal, gives None because there are none
        None,     # _header_meta protokollant, public
        0,        # _quorate member count, public
        "StuPa",  # _send gremium_name
    ]
    out = await _service(
        session, storage=storage, pytex=pytex, mail_queue=mail
    ).finalize(PID, now=NOW)

    assert out.status == "final"
    assert proto.pdf_storage_key == protocol_storage_key(PID)
    assert proto.public_pdf_storage_key == protocol_public_storage_key(PID)
    assert len(pytex.calls) == 2
    keys = {k for k, _len, _ct in storage.puts}
    assert keys == {protocol_storage_key(PID), protocol_public_storage_key(PID)}
    # The mail carries the public PDF as the attachment.
    assert len(mail.sent) == 1
    assert [a.filename for a in mail.sent[0].attachments] == ["protokoll.pdf"]


async def test_finalize_dual_render_without_storage_skips_uploads() -> None:
    """The dual-render path without storage (DEV or demo) uploads nothing.

    `_render_pdf` returns None, so there is no upload and no PDF attachment. The test
    covers the `is None` branches of the dual-render block.
    """
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),  # _get
            result(),       # internal: _assemble_from_agenda items (empty)
            result(),       # public: _assemble_from_agenda items (empty)
            result("m@x.de"),  # _recipients resolves the members
            result(),       # _recipients mail list
        ],
    )
    session.scalar_results = [
        1,        # _has_non_public is true, so the dual render runs
        None,     # _header_meta protokollant, internal
        0,        # _quorate member count, internal
        None,     # _header_meta protokollant, public
        0,        # _quorate member count, public
        "StuPa",  # _send gremium_name
    ]
    out = await _service(
        session, storage=None, pytex=FakePytex(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert proto.pdf_storage_key is None and proto.public_pdf_storage_key is None
    assert len(mail.sent) == 1 and mail.sent[0].attachments == ()


async def test_assemble_from_agenda_builds_blocks_with_votes() -> None:
    """Existing agenda items build the protocol from the bodies and the vote snippets."""
    proto = _protocol(markdown="# Fallback (sollte ignoriert werden)")
    item_with_vote = _agenda_item(title="Haushalt", body="Body Haushalt", position=1)
    item_empty = _agenda_item(
        title=None, body=None, position=2, non_public=False
    )
    vote = _vote_row(agenda_item_id=item_with_vote.id, question="Genehmigen?")
    storage = ProtoStorage()
    pytex = FakePytex(pdf=b"%PDF asm")
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium(), vote.id: vote},
        results=[
            result(proto),                 # _get
            result(item_with_vote, item_empty),  # _assemble: items
            result(vote),                  # _assemble: votes of the first item
            result(vote),                  # voting._get_vote via execute, scalar_one_or_none
            result("yes", "yes", "no"),    # voting._aggregate over the ballots
            result(),                      # _assemble: votes of the second item (empty)
            result(),                      # _recipients resolves the members (empty)
            result(),                      # _recipients mail list (empty)
        ],
    )
    session.scalar_results = [0, None, 0]  # has_non_public is 0, protokollant, members
    out = await _service(
        session, storage=storage, pytex=pytex, mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    rendered_md = pytex.calls[0][0]
    assert "# Haushalt" in rendered_md
    assert "Body Haushalt" in rendered_md
    assert "# Tagesordnungspunkt" in rendered_md  # fallback title for an empty item
    assert "[!abstimmung]" in rendered_md


async def test_assemble_public_redacts_non_public_top() -> None:
    """`public=True` replaces the body and the snippets of non-public agenda items.

    A placeholder takes their place. The heading stays, so the numbering stays stable.
    """
    proto = _protocol()
    np_item = _agenda_item(title="Personalie", body="Geheim", non_public=True)
    pub_item = _agenda_item(title="Offenes", body="Sichtbar", non_public=False)
    storage = ProtoStorage()
    pytex = FakePytex(pdf=b"%PDF red")
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),                   # _get
            result(np_item, pub_item),       # internal: items
            result(),                        # internal: votes of np_item (empty)
            result(),                        # internal: votes of pub_item (empty)
            result(np_item, pub_item),       # public: items
            result(),                        # public: votes of pub_item, np_item skipped
            result(),                        # _recipients members
            result(),                        # _recipients mail list
        ],
    )
    session.scalar_results = [1, None, 0, None, 0, "StuPa"]
    await _service(
        session, storage=storage, pytex=pytex, mail_queue=None
    ).finalize(PID, now=NOW)
    internal_md = pytex.calls[0][0]
    public_md = pytex.calls[1][0]
    assert "Geheim" in internal_md
    assert "Geheim" not in public_md
    assert "nicht-öffentlicher Tagesordnungspunkt" in public_md
    # AUD-025: a non-public title can encode the subject. The internal variant keeps it.
    # The public variant replaces it with a neutral heading. The single top-level `#`
    # keeps the numbering stable.
    assert "# Personalie" in internal_md
    assert "# Personalie" not in public_md
    assert "# Nicht-öffentlicher Tagesordnungspunkt" in public_md


async def test_assemble_skips_cancelled_votes_in_query() -> None:
    """A cancelled vote gives no snippet.

    The SELECT filters it out. An empty result covers the branch.
    """
    proto = _protocol()
    item = _agenda_item(title="X", body=None)
    storage = ProtoStorage()
    pytex = FakePytex()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[
            result(proto),
            result(item),   # items
            result(),       # votes (all cancelled, so empty)
            result(),       # members
            result(),       # mail list
        ],
    )
    session.scalar_results = [0, None, 0]
    out = await _service(
        session, storage=storage, pytex=pytex, mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert "[!abstimmung]" not in pytex.calls[0][0]


async def test_quorate_with_explicit_percent_threshold() -> None:
    """A set gremium.quorum_percent gives the threshold present*100 >= percent*members."""
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [10]  # 10 members
    gremium = _gremium(quorum_percent=50)
    # 5 present, 50% of 10 is 5, so 500 >= 500 is true.
    assert await svc._quorate(gremium, present_count=5) is True


async def test_quorate_percent_not_met() -> None:
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [10]
    gremium = _gremium(quorum_percent=60)
    # 5 present, 60% of 10 is 6, so 500 >= 600 is false.
    assert await svc._quorate(gremium, present_count=5) is False


async def test_quorate_default_majority_rule() -> None:
    """Without quorum_percent the rule is more than half (present*2 > members)."""
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [10]
    gremium = _gremium(quorum_percent=None)
    assert await svc._quorate(gremium, present_count=6) is True
    session.scalar_results = [10]
    assert await svc._quorate(gremium, present_count=5) is False


async def test_quorate_none_without_gremium() -> None:
    svc = _service(FakeSession())
    assert await svc._quorate(None, present_count=3) is None


async def test_quorate_none_without_members() -> None:
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = [0]  # no members
    assert await svc._quorate(_gremium(), present_count=3) is None


async def test_quorate_none_when_member_count_query_returns_none() -> None:
    """`session.scalar` returns None, so `or 0` makes members 0 and the result None."""
    svc = _service(FakeSession())
    # An empty scalar_results makes scalar() return None, so the `or 0` applies.
    assert await svc._quorate(_gremium(), present_count=3) is None


async def test_header_meta_returns_empty_without_meeting() -> None:
    svc = _service(FakeSession())
    protokollant, present, absent, count, datalines = await svc._header_meta(None)
    assert protokollant is None and present == [] and absent == []
    assert count == 0 and datalines == []


async def test_header_meta_resolves_protokollant_name() -> None:
    """A set protokollant_id resolves the name through `session.scalar`."""
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = ["Frau Schmidt"]
    meeting = _meeting(protokollant_id=uuid4())
    protokollant, present, absent, count, datalines = await svc._header_meta(
        cast("Any", meeting)
    )
    assert protokollant == "Frau Schmidt"
    # The FakeSession short circuits the attendance query, so it stays empty.
    assert present == [] and absent == [] and count == 0 and datalines == []


async def test_header_meta_public_redacts_names_keeps_counts() -> None:
    """AUD-025: `public=True` drops the protokollant and the name lists.

    Only the counters stay, as data lines. The true `present_count` stays correct.
    """
    session = FakeSession()
    svc = _service(session)
    session.scalar_results = ["Frau Schmidt"]
    meeting = _meeting(protokollant_id=uuid4())
    protokollant, present, absent, count, datalines = await svc._header_meta(
        cast("Any", meeting), public=True
    )
    assert protokollant is None
    assert present == [] and absent == []
    # The fake attendance is empty, so both counters are 0.
    assert count == 0
    assert datalines == ["Anwesend: 0", "Abwesend: 0"]


def test_local_end_time_none_when_not_datetime() -> None:
    svc = _service(FakeSession())
    assert svc._local_end_time(None) is None
    assert svc._local_end_time("not-a-datetime") is None


def test_local_end_time_converts_utc_to_local() -> None:
    svc = _service(FakeSession())
    closed = datetime(2026, 6, 12, 17, 30, 45, tzinfo=UTC)  # 19:30 in Berlin, summer time
    end = svc._local_end_time(closed)
    assert isinstance(end, _time)
    assert end == _time(19, 30)  # seconds and microseconds zeroed


async def test_finalize_uses_meeting_closed_at_end_time() -> None:
    """The full finalize path with a set closed_at activates `_local_end_time`."""
    proto = _protocol()
    meeting = _meeting(closed_at=datetime(2026, 6, 12, 17, 30, tzinfo=UTC))
    storage = ProtoStorage()
    pytex = FakePytex()
    session = FakeSession(
        store={MID: meeting, GID: _gremium()},
        results=[result(proto), result(), result(), result()],
    )
    session.scalar_results = [0, None, 0]
    out = await _service(
        session, storage=storage, pytex=pytex, mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"


async def test_finalize_non_retryable_pytex_error_400() -> None:
    proto = _protocol()
    pytex = FakePytex(error=PytexError("bad latex", retryable=False))
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result()],
    )
    session.scalar_results = [0, None, 0]
    with pytest.raises(BadRequestError) as exc:
        await _service(session, storage=ProtoStorage(), pytex=pytex).finalize(
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
            session, storage=FailingStorage(), pytex=FakePytex()
        ).finalize(PID, now=NOW)


async def test_send_subject_and_body_include_gremium_and_date() -> None:
    """The subject and the body carry the Gremium, the meeting and the date."""
    proto = _protocol()
    meeting = _meeting()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: meeting, GID: _gremium()},
        results=[
            result(proto),
            result(),                 # _assemble items (empty)
            result("a@x.de"),         # members
            result(),                 # mail list
        ],
    )
    # has_non_public is false, then the quorate member count, then gremium_name for
    # _send. _meeting sets protokollant_id to None, so no protokollant scalar is read.
    session.scalar_results = [0, 5, "StuPa"]
    await _service(
        session, storage=ProtoStorage(), pytex=FakePytex(), mail_queue=mail
    ).finalize(PID, now=NOW)
    msg = mail.sent[0]
    assert "StuPa" in msg.subject
    assert "12.06.2026" in msg.subject
    assert "Sitzung: StuPa-Sitzung" in msg.text
    assert "Gremium: StuPa" in msg.text
    assert "Datum: 12.06.2026" in msg.text
    assert "liegt als PDF bei" in msg.text  # the PDF attachment hint


async def test_send_without_gremium_name_and_meeting() -> None:
    """No Gremium name and no meeting give a lean subject and body without a PDF hint."""
    proto = _protocol()
    mail = FakeMailQueue()
    # The store holds no meeting, so meeting is None and the gremium_name scalar is None.
    session = FakeSession(
        store={GID: _gremium(name=None)},
        results=[
            result(proto),
            result(),         # _assemble items (no meeting, so empty markdown fallback)
            result("a@x.de"),  # members
            result(),         # mail list
        ],
    )
    # has_non_public is 0, then the quorate member count. Meeting is None, so no
    # protokollant scalar is read. Then gremium_name is None.
    session.scalar_results = [0, 5, None]
    # Without storage there is no PDF, so the intro drops the hint and no file travels.
    await _service(
        session, storage=None, pytex=FakePytex(), mail_queue=mail
    ).finalize(PID, now=NOW)
    msg = mail.sent[0]
    assert msg.subject == "Sitzungsprotokoll"  # neither Gremium nor date
    assert "liegt als PDF bei" not in msg.text
    assert msg.attachments == ()


async def test_embed_vote_title_for_application_reference() -> None:
    """A set application_id makes the snippet title reference the application."""
    app_id = uuid4()
    vid = uuid4()
    proto = _protocol(markdown="# TOP 1")
    # With question None, build_vote_snippet uses the _vote_title application reference.
    vote = _vote_row(id=vid, application_id=app_id, question=None)
    session = FakeSession(
        store={vid: vote},
        results=[
            result(proto),       # _get
            result(),            # existing refs (none)
            result(uuid4()),     # pg_insert RETURNING id
            result(vote),        # voting._get_vote
            result("yes", "no"),  # voting._aggregate
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
    proto = _protocol(markdown="# Bestehendes Markdown")
    pytex = FakePytex()
    # The store holds no meeting and no gremium, so both resolve to None.
    session = FakeSession(
        store={},
        results=[result(proto), result(), result(), result()],
    )
    session.scalar_results = [0]  # has_non_public is false. Without a gremium: None.
    out = await _service(
        session, storage=ProtoStorage(), pytex=pytex, mail_queue=None
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    # The build falls back to protocol.markdown because there are no agenda items.
    assert "# Bestehendes Markdown" in pytex.calls[0][0]


# PdfService.load_application_doc and its helpers.
class _Result:
    """Minimal wrapper for an execute or scalars result."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def scalars(self) -> _Result:
        return self


class _PdfDocSession:
    """Session fake for `load_application_doc` with get, scalar, scalars and execute."""

    def __init__(
        self,
        *,
        store: dict[uuid.UUID, Any],
        scalars: list[list[Any]],
        scalar: list[Any],
        executes: list[list[Any]],
    ) -> None:
        self.store = store
        self._scalars = scalars
        self._scalar = scalar
        self._executes = executes

    async def get(self, _model: type, ident: uuid.UUID) -> Any:
        return self.store.get(ident)

    async def scalar(self, _stmt: Any) -> Any:
        return self._scalar.pop(0) if self._scalar else None

    async def scalars(self, _stmt: Any) -> _Result:
        return _Result(self._scalars.pop(0) if self._scalars else [])

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._executes.pop(0) if self._executes else [])


def _field_row(key: str = "betrag") -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        type="text",
        label_i18n={"de": "Betrag"},
        help_i18n=None,
        required=True,
        validation=None,
        visible_if=None,
        compute=None,
        options=None,
        is_pii=False,
        is_promoted=False,
        promote_target=None,
    )


def _make_app(**over: Any) -> Application:
    app = Application()
    app.id = over.pop("id", uuid4())
    app.type_id = over.pop("type_id", uuid4())
    app.form_version_id = over.pop("form_version_id", uuid4())
    app.gremium_id = over.pop("gremium_id", None)
    app.data = over.pop("data", {"betrag": "100"})
    app.lang = over.pop("lang", None)
    app.created_at = over.pop("created_at", NOW)
    for k, v in over.items():
        setattr(app, k, v)
    return app


async def test_load_application_doc_full_with_gremium_timeline_vote() -> None:
    app_id = uuid4()
    type_id = uuid4()
    gremium_id = uuid4()
    app = _make_app(
        id=app_id, type_id=type_id, gremium_id=gremium_id, lang=None,
        data={"betrag": "100"},
    )
    app_type = SimpleNamespace(name_i18n={"de": "Finanzantrag"}, key="finanz")
    gremium = SimpleNamespace(
        default_lang="de", slug="stupa", cd_variant="stupa"
    )
    state = SimpleNamespace(label_i18n={"de": "Bewilligt"}, key="approved")
    event = SimpleNamespace(at=NOW, to_state_id=uuid4(), note="ok")
    vote = SimpleNamespace(
        config={"title": {"de": "Finanzierung"}}, result="passed"
    )
    session = _PdfDocSession(
        store={app_id: app, type_id: app_type, gremium_id: gremium},
        scalars=[[_field_row()]],          # _fields
        scalar=["Max Muster", vote],       # applicant_name, _vote_result
        executes=[[(event, state)]],       # _timeline rows
    )
    doc = await PdfService(session).load_application_doc(app_id)  # type: ignore[arg-type]
    assert doc.type_name == "Finanzantrag"
    assert doc.gremium_slug == "stupa"
    assert doc.cd_variant == "stupa"
    assert doc.lang == "de"
    assert doc.applicant_name == "Max Muster"
    assert len(doc.fields) == 1 and doc.fields[0].key == "betrag"
    assert len(doc.timeline) == 1
    assert doc.timeline[0].state_label == "Bewilligt"
    assert doc.timeline[0].note == "ok"
    assert doc.vote is not None and doc.vote.title == "Finanzierung"
    assert doc.vote.result == "passed"


async def test_load_application_doc_no_gremium_uses_de_and_type_key() -> None:
    """Without a Gremium the default_lang is 'de'.

    An empty `app_type.name_i18n` falls back to the key.
    """
    app_id = uuid4()
    type_id = uuid4()
    app = _make_app(id=app_id, type_id=type_id, gremium_id=None, lang="en")
    app_type = SimpleNamespace(name_i18n={}, key="generic")
    session = _PdfDocSession(
        store={app_id: app, type_id: app_type},
        scalars=[[]],          # _fields (none)
        scalar=[None, None],   # applicant_name None, _vote_result None
        executes=[[]],         # _timeline (none)
    )
    doc = await PdfService(session).load_application_doc(app_id)  # type: ignore[arg-type]
    assert doc.gremium_slug is None
    assert doc.cd_variant is None
    assert doc.lang == "en"            # app.lang wins
    assert doc.default_lang == "de"
    assert doc.type_name == "generic"  # key fallback
    assert doc.applicant_name is None
    assert doc.timeline == []
    assert doc.vote is None


async def test_load_application_doc_missing_app_type_falls_back_to_antrag() -> None:
    """A missing app_type in the store gives the type_name 'Antrag'."""
    app_id = uuid4()
    app = _make_app(id=app_id, gremium_id=None, lang=None)
    session = _PdfDocSession(
        store={app_id: app},  # no app_type
        scalars=[[]],
        scalar=[None, None],
        executes=[[]],
    )
    doc = await PdfService(session).load_application_doc(app_id)  # type: ignore[arg-type]
    assert doc.type_name == "Antrag"
    assert doc.lang == "de"  # no app.lang and no gremium, so the default 'de'


async def test_load_application_doc_unknown_application_404() -> None:
    session = _PdfDocSession(store={}, scalars=[], scalar=[], executes=[])
    with pytest.raises(NotFoundError):
        await PdfService(session).load_application_doc(uuid4())  # type: ignore[arg-type]


async def test_vote_result_none_when_no_vote() -> None:
    """_vote_result returns None when there is no vote."""
    app_id = uuid4()
    app = _make_app(id=app_id, gremium_id=None)
    session = _PdfDocSession(
        store={app_id: app},
        scalars=[[]],
        scalar=[None, None],  # applicant None, vote None
        executes=[[]],
    )
    doc = await PdfService(session).load_application_doc(app_id)  # type: ignore[arg-type]
    assert doc.vote is None


async def test_vote_result_string_title_and_default_title() -> None:
    """A raw_title that is already a string stays.

    Without a title key the result falls back to 'Abstimmung'.
    """
    svc = PdfService(_PdfDocSession(store={}, scalars=[], scalar=[], executes=[]))  # type: ignore[arg-type]
    vote_str = SimpleNamespace(config={"title": "Direkt"}, result="passed")
    svc.session._scalar = [vote_str]  # type: ignore[attr-defined]
    res = await svc._vote_result(uuid4(), "de", "de")
    assert res is not None and res.title == "Direkt"
    # A missing title key gives the default "Abstimmung".
    vote_no_title = SimpleNamespace(config={}, result="rejected")
    svc.session._scalar = [vote_no_title]  # type: ignore[attr-defined]
    res2 = await svc._vote_result(uuid4(), "de", "de")
    assert res2 is not None and res2.title == "Abstimmung"
    assert res2.result == "rejected"
    # A config that is not a dict gives raw_title None, so the default applies.
    vote_bad_cfg = SimpleNamespace(config=None, result="passed")
    svc.session._scalar = [vote_bad_cfg]  # type: ignore[attr-defined]
    res3 = await svc._vote_result(uuid4(), "de", "de")
    assert res3 is not None and res3.title == "Abstimmung"


async def test_vote_result_none_when_result_none() -> None:
    """A vote whose result is None gives None."""
    svc = PdfService(_PdfDocSession(store={}, scalars=[], scalar=[], executes=[]))  # type: ignore[arg-type]
    vote = SimpleNamespace(config={"title": "X"}, result=None)
    svc.session._scalar = [vote]  # type: ignore[attr-defined]
    assert await svc._vote_result(uuid4(), "de", "de") is None


async def test_timeline_uses_state_key_when_label_missing() -> None:
    """_timeline falls back to state.key when label_i18n is empty."""
    svc = PdfService(_PdfDocSession(store={}, scalars=[], scalar=[], executes=[]))  # type: ignore[arg-type]
    state = SimpleNamespace(label_i18n={}, key="draft")
    event = SimpleNamespace(at=NOW, to_state_id=uuid4(), note=None)
    svc.session._executes = [[(event, state)]]  # type: ignore[attr-defined]
    items = await svc._timeline(uuid4(), "de", "de")
    assert len(items) == 1
    assert items[0].state_label == "draft"
    assert items[0].note is None


# FilesService: list_for_application, delete and delete_for_application.
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
        is_comparison_offer=False,
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
        is_comparison_offer=False,
    )
    a1.id = uuid.uuid4()
    a2 = Attachment(
        application_id=uuid.uuid4(), filename="b.pdf", mime="application/pdf",
        size=2, storage_key="k2", scanned=False, scan_result=None,
        is_comparison_offer=True,
    )
    a2.id = uuid.uuid4()
    session._scalars = [[a1, a2]]
    out = await _files_service(session, storage=FakeStorage()).list_for_application(
        uuid.uuid4()
    )
    assert [o.filename for o in out] == ["a.pdf", "b.pdf"]
    assert out[1].is_comparison_offer is True


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
    assert att in session.deleted  # the DB row is gone
    assert storage.removed == ["k/doc.pdf"]
    assert session.committed == 1
    assert calls and calls[0]["target_type"] == "attachment"
    assert calls[0]["actor"] == "admin"


async def test_delete_tolerates_storage_remove_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delete call swallows a storage remove error as a best effort."""
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = _FilesSession()
    att = _attachment(session)
    svc = _files_service(session, storage=FailingStorage())
    await svc.delete(att.id, actor="admin")  # must NOT raise
    assert session.committed == 1


async def test_delete_without_storage_or_key_skips_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delete call tries no remove without a storage or without a storage_key."""
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    # Case 1: no storage.
    session = _FilesSession()
    att = _attachment(session)
    await _files_service(session, storage=None).delete(att.id, actor="a")
    assert session.committed == 1
    # Case 2: a storage is there, but storage_key is None.
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
    """delete_for_application removes every row and object, audits, and never commits."""
    calls: list[dict[str, object]] = []

    async def _record(session: object, **kw: object) -> None:
        calls.append(kw)

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = _FilesSession()
    a1 = _attachment(session, storage_key="k/1")
    a2 = _attachment(session, storage_key=None)  # without a storage object
    session._scalars = [[a1, a2]]
    storage = FakeStorage()
    storage.objects["k/1"] = (b"x", "application/pdf")
    n = await _files_service(session, storage=storage).delete_for_application(
        uuid.uuid4(), actor="dsgvo"
    )
    assert n == 2
    assert storage.removed == ["k/1"]  # only a1 had a key
    assert len(calls) == 2  # two audit entries
    assert session.committed == 0  # does NOT commit on its own


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


async def test_upload_with_field_key_and_comparison_offer() -> None:
    """An upload with field_key and is_comparison_offer sets both on the row."""
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
        is_comparison_offer=True,
    )
    assert out.is_comparison_offer is True
    added = [a for a in session.added if isinstance(a, Attachment)]
    assert added and added[0].field_key == "kostenaufstellung"
    assert len(queue.enqueued) == 1
