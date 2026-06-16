"""Unit-Tests Worker-Task render_protocol (T-22 async): Erfolg, Retry, Rollback.

Kein Redis im ctx → Mail-Queue ``None`` (Versand übersprungen) und der
``meeting_state``-Broadcast wird ausgelassen; der Fokus liegt auf dem
Status-Lebenszyklus ``rendering → final`` bzw. ``rendering → draft`` (Rollback).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from arq import Retry

from app.modules.pdf.pytex_client import PytexError
from app.modules.protocol.models import Protocol
from app.settings import load_settings
from tests._support.pdf_fakes import FakePytex, FakeSessionmaker
from tests._support.protocol_fakes import FakeSession, FakeStorage, result
from worker.protocol import render_protocol

PID = uuid4()
MID = uuid4()
GID = uuid4()


def _protocol(status: str = "rendering") -> Protocol:
    proto = Protocol(
        meeting_id=MID, gremium_id=GID, markdown="# Body", status=status
    )
    proto.id = PID
    return proto


def _ctx(
    session: FakeSession, *, pytex: FakePytex, storage: object | None, job_try: int = 1
) -> dict[str, Any]:
    return {
        "settings": load_settings(pdf_max_tries=3, pdf_retry_backoff_seconds=10),
        "pytex_client": pytex,
        "object_storage": storage,
        "protocol_sessionmaker": FakeSessionmaker(session),  # type: ignore[arg-type]
        "job_try": job_try,
        # kein "redis": Mail-Queue None + Broadcast übersprungen (Unit-Fokus Status).
    }


async def test_render_protocol_success_finalizes() -> None:
    proto = _protocol()
    # execute-Reihenfolge: _get → _assemble_from_agenda (leer) → Broadcast entfällt.
    session = FakeSession(store={}, results=[result(proto), result()])
    ctx = _ctx(session, pytex=FakePytex(), storage=FakeStorage())
    assert await render_protocol(ctx, str(PID)) == "final"
    assert proto.status == "final"
    assert proto.sent_at is not None


async def test_render_protocol_transient_retries() -> None:
    proto = _protocol()
    pytex = FakePytex(error=PytexError("5xx", status=503, retryable=True))
    session = FakeSession(store={}, results=[result(proto), result()])
    ctx = _ctx(session, pytex=pytex, storage=FakeStorage(), job_try=1)
    with pytest.raises(Retry):
        await render_protocol(ctx, str(PID))
    assert proto.status == "rendering"  # Retry kommt — kein Rollback


async def test_render_protocol_exhausted_reverts_to_draft() -> None:
    proto = _protocol()
    pytex = FakePytex(error=PytexError("5xx", status=503, retryable=True))
    # _get (finalize) → _assemble → _get (revert_to_draft)
    session = FakeSession(
        store={}, results=[result(proto), result(), result(proto)]
    )
    ctx = _ctx(session, pytex=pytex, storage=FakeStorage(), job_try=3)
    assert await render_protocol(ctx, str(PID)) == "dead"
    assert proto.status == "draft"  # re-finalisierbar, nie in rendering hängen


async def test_render_protocol_permanent_error_reverts_to_draft() -> None:
    """pytex 4xx (Compile-Fehler) = dauerhaft → sofortiger Rollback, kein Retry."""
    proto = _protocol()
    pytex = FakePytex(error=PytexError("bad latex", status=400, retryable=False))
    session = FakeSession(
        store={}, results=[result(proto), result(), result(proto)]
    )
    ctx = _ctx(session, pytex=pytex, storage=FakeStorage(), job_try=1)
    assert await render_protocol(ctx, str(PID)) == "failed"
    assert proto.status == "draft"


async def test_render_protocol_already_final_is_noop() -> None:
    """Doppelt enqueueter Job: ``finalize`` ist idempotent — kein zweiter Render."""
    proto = _protocol(status="final")
    pytex = FakePytex()
    session = FakeSession(store={}, results=[result(proto)])
    ctx = _ctx(session, pytex=pytex, storage=FakeStorage())
    assert await render_protocol(ctx, str(PID)) == "final"
    assert pytex.calls == []
