"""Unit-Tests ProtocolService (T-22): Lebenszyklus + Vote-Einbettung + finalize.

Ohne DB/pytex/MinIO/Redis: ``session.get`` aus einem Store, ``execute`` aus einer
geordneten Ergebnis-Queue (Branch-Abdeckung). Die echten DB-Constraints (UNIQUE
meeting_id / vote_ref) liegen in der Integration."""

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
from tests.pdf_fakes import FakeNextcloud, FakePytex
from tests.protocol_fakes import FakeMailQueue, FakeSession, FakeStorage, result

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


def _real_gremium(cd_variant: str = "stupa") -> Gremium:
    gremium = Gremium(name="StuPa", slug="stupa", cd_variant=cd_variant)
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


# --------------------------------------------------------------- get_or_create
def test_insert_values_inherits_cd_variant_and_gremium() -> None:
    meeting = _real_meeting()
    values = ProtocolService._insert_values(meeting, _real_gremium("asta"), "p1")
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
        store={MID: _real_meeting(), GID: _real_gremium("asta")},
        # execute-Reihenfolge: _by_meeting(leer) → pg_insert(ignoriert) → _by_meeting(neu)
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
    assert session.committed == 0  # reiner Read, kein Insert/Commit


async def test_get_or_create_concurrent_insert_reselects_winner() -> None:
    """Parallel-POST: eigenes ON-CONFLICT-Insert no-opt, Re-Select liefert Gewinner-Zeile."""
    winner = _protocol(markdown="# vom Parallel-Request")
    session = FakeSession(
        store={MID: _real_meeting(), GID: _real_gremium()},
        results=[result(), result(), result(winner)],
    )
    out = await _service(session).get_or_create(MID)
    assert out.markdown == "# vom Parallel-Request"


async def test_get_or_create_unknown_meeting_404() -> None:
    session = FakeSession(store={}, results=[result()])
    with pytest.raises(NotFoundError):
        await _service(session).get_or_create(MID)


async def test_get_or_create_vanished_after_insert_404() -> None:
    """Defensiv: Zeile zwischen Insert und Re-Select verschwunden → 404 statt None-Deref."""
    session = FakeSession(
        store={MID: _real_meeting(), GID: _real_gremium()},
        results=[result(), result(), result()],  # kein bestehendes, Insert, Re-Select leer
    )
    with pytest.raises(NotFoundError):
        await _service(session).get_or_create(MID)


# --------------------------------------------------------------- update_markdown
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
    session = FakeSession(results=[result()])  # _get findet nichts
    with pytest.raises(NotFoundError):
        await _service(session).update_markdown(PID, "# Neu")


# ------------------------------------------------------------------ embed_votes
async def test_embed_votes_appends_snippet_and_ref() -> None:
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(
        store={VID: _vote()},
        results=[
            result(proto),  # _get
            result(),  # bestehende Refs (keine)
            result(uuid4()),  # pg_insert ProtocolVoteRef → RETURNING id (eingefügt)
            result(_vote()),  # VotingService._get_vote
            result("yes", "yes", "no"),  # VotingService._aggregate
        ],
    )
    out = await _service(session).embed_votes(PID, [VID])
    assert "### Abstimmung" in out.markdown
    assert "**Ergebnis:** passed" in out.markdown
    assert "yes: 2, no: 1" in out.markdown
    assert session.committed == 1


async def test_embed_votes_idempotent_skips_referenced() -> None:
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(
        results=[result(proto), result(VID)]  # VID bereits referenziert (pre-query)
    )
    out = await _service(session).embed_votes(PID, [VID])
    assert out.markdown == "# TOP 1"  # unverändert


async def test_embed_votes_concurrent_ref_skips_snippet() -> None:
    """Parallel-Insert gewinnt: ON CONFLICT liefert kein RETURNING → kein Doppel-Snippet."""
    proto = _protocol(markdown="# TOP 1")
    session = FakeSession(
        store={VID: _vote()},
        results=[
            result(proto),  # _get
            result(),  # bestehende Refs (keine, pre-query)
            result(),  # pg_insert → RETURNING leer (Konflikt: nebenläufig eingefügt)
        ],
    )
    out = await _service(session).embed_votes(PID, [VID])
    assert out.markdown == "# TOP 1"  # unverändert


async def test_embed_votes_unknown_vote_404() -> None:
    session = FakeSession(store={}, results=[result(_protocol()), result()])
    with pytest.raises(NotFoundError):
        await _service(session).embed_votes(PID, [VID])


async def test_embed_votes_on_final_conflict() -> None:
    session = FakeSession(results=[result(_protocol(status="final"))])
    with pytest.raises(ConflictError):
        await _service(session).embed_votes(PID, [VID])


# --------------------------------------------------------------------- finalize
async def test_finalize_renders_stores_and_mails() -> None:
    proto = _protocol()
    storage = FakeStorage()
    pytex = FakePytex(pdf=b"%PDF-1.4 ok")
    nextcloud = FakeNextcloud()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium("stupa")},
        results=[result(proto), result(["a@x.de", "b@x.de"])],
    )
    out = await _service(
        session, storage=storage, pytex=pytex, nextcloud=nextcloud, mail_queue=mail
    ).finalize(PID, now=NOW)

    assert out.status == "final"
    assert out.sent_at == NOW
    assert proto.pdf_storage_key == protocol_storage_key(PID)
    assert proto.nextcloud_path is not None
    assert storage.puts and storage.puts[0][2] == "application/pdf"
    assert pytex.calls and pytex.calls[0][1] == "protocol-stupa"
    assert out.pdf_url is not None
    assert len(mail.sent) == 1
    assert mail.sent[0].to == ("a@x.de", "b@x.de")
    assert "PDF:" in mail.sent[0].text


async def test_finalize_without_storage_degrades_but_mails() -> None:
    proto = _protocol()
    pytex = FakePytex()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result(["a@x.de"])],
    )
    out = await _service(session, storage=None, pytex=pytex, mail_queue=mail).finalize(
        PID, now=NOW
    )
    assert out.status == "final"
    assert out.pdf_url is None
    assert proto.pdf_storage_key is None
    assert pytex.calls == []  # Render übersprungen (kein Storage)
    assert len(mail.sent) == 1 and "PDF:" not in mail.sent[0].text


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
    assert out.pdf_url is not None  # frisch signiert aus Bestands-Key
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
    assert proto.status == "draft"  # Entwurf bleibt erhalten


async def test_finalize_no_recipients_skips_mail() -> None:
    proto = _protocol()
    mail = FakeMailQueue()
    session = FakeSession(
        store={MID: _meeting(), GID: _gremium()},
        results=[result(proto), result()],  # leere Verteilerliste
    )
    out = await _service(
        session, storage=FakeStorage(), pytex=FakePytex(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert out.status == "final"
    assert mail.sent == []


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
        results=[result(proto), result(["a@x", "b@x"], ["b@x", "c@x"])],
    )
    await _service(
        session, storage=FakeStorage(), pytex=FakePytex(), mail_queue=mail
    ).finalize(PID, now=NOW)
    assert mail.sent[0].to == ("a@x", "b@x", "c@x")
