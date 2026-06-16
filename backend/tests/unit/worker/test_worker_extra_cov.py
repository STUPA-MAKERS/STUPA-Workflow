"""Zusatz-Unit-Deckung der Worker-Tasks (retention/scan/pdf/mail/webhook/main/
task_reminders/deadlines) — alle Branches/Fehlerpfade ohne DB/Redis/Netz.

Ergänzt die bestehenden Worker-Tests gezielt um die noch ungedeckten Zeilen:
``_on_startup``-Orchestrierung, scan-/pdf-Task inkl. Retry/Dead, DSGVO-Retention
(anonymisieren + purgen, Per-Zeile-Fehlerisolation), Deadline-Auto-Transitionen
und die Rand-Branches der Task-Erinnerungen.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from arq import Retry
from freezegun import freeze_time

import worker.deadlines as wd
import worker.main as wmain
import worker.pdf as wpdf
import worker.retention as wret
import worker.scan as wscan
import worker.task_reminders as wtr
from app.modules.files.scanner import ScannerError, ScanVerdict
from app.modules.files.storage import StorageError
from app.modules.notifications.models import NotificationSettings, TaskReminderLog
from app.modules.pdf.render import RenderRetry
from app.settings import load_settings
from app.shared.errors import ConflictError, NotFoundError
from tests._support.notifications_fakes import FakeQueue
from tests._support.notifications_fakes import FakeSession as NotifFakeSession

SETTINGS = load_settings()
NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Gemeinsame Session-/Sessionmaker-Fakes
# --------------------------------------------------------------------------- #
class _SessionCM:
    """Async-Context-Manager um eine beliebige Fake-Session."""

    def __init__(self, session: Any) -> None:
        self.session = session

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _maker(session: Any) -> Any:
    """Sessionmaker-Fake, der immer dieselbe Session liefert."""
    return lambda: _SessionCM(session)


# =========================================================================== #
# worker/scan.py
# =========================================================================== #
class _ScanSession:
    """Minimal-Session: ``get`` aus dem Store."""

    def __init__(self, store: dict[uuid.UUID, Any] | None = None) -> None:
        self.store = store or {}

    async def get(self, _model: type, ident: uuid.UUID) -> Any:
        return self.store.get(ident)


class _FinalizeFilesService:
    """Fängt ``finalize_scan`` ab (keine echte DB-Logik)."""

    calls: list[tuple[uuid.UUID, ScanVerdict, str]] = []

    def __init__(self, *_a: Any, **_k: Any) -> None: ...

    async def finalize_scan(
        self, aid: uuid.UUID, verdict: ScanVerdict, *, actor: str = "system"
    ) -> None:
        _FinalizeFilesService.calls.append((aid, verdict, actor))


@pytest.fixture(autouse=True)
def _reset_scan() -> Any:
    _FinalizeFilesService.calls = []
    yield


async def test_scan_on_startup_populates_ctx() -> None:
    ctx: dict[str, Any] = {}
    await wscan.on_startup(ctx)
    assert "settings" in ctx
    # Default-Settings → kein clamav/MinIO konfiguriert → None.
    assert ctx["scanner"] is None
    assert ctx["object_storage"] is None


def test_scan_sessionmaker_default_and_injected() -> None:
    assert wscan._sessionmaker({}) is not None
    sentinel = object()
    assert wscan._sessionmaker({"files_sessionmaker": sentinel}) is sentinel


async def test_scan_skipped_when_scanner_or_storage_missing() -> None:
    # scanner fehlt → skipped (keine DB-Berührung).
    ctx = {"settings": SETTINGS, "scanner": None, "object_storage": object()}
    assert await wscan.scan_attachment(ctx, str(uuid4())) == "skipped"
    # storage fehlt → ebenfalls skipped.
    ctx2 = {"settings": SETTINGS, "scanner": object(), "object_storage": None}
    assert await wscan.scan_attachment(ctx2, str(uuid4())) == "skipped"


async def test_scan_gone_when_attachment_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wscan, "FilesService", _FinalizeFilesService)
    session = _ScanSession()  # leerer Store → get liefert None
    ctx = {
        "settings": SETTINGS,
        "scanner": object(),
        "object_storage": object(),
        "files_sessionmaker": _maker(session),
    }
    assert await wscan.scan_attachment(ctx, str(uuid4())) == "gone"


async def test_scan_gone_when_storage_key_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wscan, "FilesService", _FinalizeFilesService)
    aid = uuid4()
    attachment = SimpleNamespace(id=aid, storage_key=None)
    session = _ScanSession({aid: attachment})
    ctx = {
        "settings": SETTINGS,
        "scanner": object(),
        "object_storage": object(),
        "files_sessionmaker": _maker(session),
    }
    assert await wscan.scan_attachment(ctx, str(aid)) == "gone"


async def test_scan_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wscan, "FilesService", _FinalizeFilesService)
    aid = uuid4()
    attachment = SimpleNamespace(id=aid, storage_key="k/obj")
    session = _ScanSession({aid: attachment})

    class _Storage:
        async def get(self, key: str) -> bytes:
            assert key == "k/obj"
            return b"data"

    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            assert data == b"data"
            return ScanVerdict(clean=True)

    ctx = {
        "settings": SETTINGS,
        "scanner": _Scanner(),
        "object_storage": _Storage(),
        "files_sessionmaker": _maker(session),
    }
    assert await wscan.scan_attachment(ctx, str(aid)) == "clean"
    assert _FinalizeFilesService.calls[0][0] == aid
    assert _FinalizeFilesService.calls[0][1].clean is True


async def test_scan_infected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wscan, "FilesService", _FinalizeFilesService)
    aid = uuid4()
    attachment = SimpleNamespace(id=aid, storage_key="k/obj")
    session = _ScanSession({aid: attachment})

    class _Storage:
        async def get(self, key: str) -> bytes:
            return b"evil"

    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            return ScanVerdict(clean=False, signature="EICAR")

    ctx = {
        "settings": SETTINGS,
        "scanner": _Scanner(),
        "object_storage": _Storage(),
        "files_sessionmaker": _maker(session),
    }
    assert await wscan.scan_attachment(ctx, str(aid)) == "infected"


async def test_scan_storage_error_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wscan, "FilesService", _FinalizeFilesService)
    aid = uuid4()
    attachment = SimpleNamespace(id=aid, storage_key="k/obj")
    session = _ScanSession({aid: attachment})

    class _Storage:
        async def get(self, key: str) -> bytes:
            raise StorageError("down")

    ctx = {
        "settings": load_settings(scan_max_tries=5, scan_retry_backoff_seconds=7),
        "scanner": SimpleNamespace(),
        "object_storage": _Storage(),
        "files_sessionmaker": _maker(session),
        "job_try": 1,
    }
    with pytest.raises(Retry):
        await wscan.scan_attachment(ctx, str(aid))


async def test_scan_scanner_error_dead_after_max_tries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wscan, "FilesService", _FinalizeFilesService)
    aid = uuid4()
    attachment = SimpleNamespace(id=aid, storage_key="k/obj")
    session = _ScanSession({aid: attachment})

    class _Storage:
        async def get(self, key: str) -> bytes:
            return b"x"

    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            raise ScannerError("clamav down")

    ctx = {
        "settings": load_settings(scan_max_tries=3),
        "scanner": _Scanner(),
        "object_storage": _Storage(),
        "files_sessionmaker": _maker(session),
        "job_try": 3,
    }
    assert await wscan.scan_attachment(ctx, str(aid)) == "dead"


def test_scan_retry_or_dead_default_job_try() -> None:
    # job_try fehlt → Default 1; max_tries=5 → Retry mit Backoff job_try*backoff.
    settings = load_settings(scan_max_tries=5, scan_retry_backoff_seconds=11)
    with pytest.raises(Retry) as ei:
        wscan._retry_or_dead({}, settings, "aid", RuntimeError("boom"))
    assert ei.value.defer_score == 11_000  # job_try(1) * backoff(11s), in ms


# =========================================================================== #
# worker/pdf.py
# =========================================================================== #
class _Pipeline:
    """RenderPipeline-Fake: run liefert Status oder wirft RenderRetry."""

    def __init__(self, *, result: str = "done", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.failed: list[tuple[uuid.UUID, str]] = []

    async def run(self, jid: uuid.UUID) -> str:
        if self.error is not None:
            raise self.error
        return self.result

    async def mark_failed(self, jid: uuid.UUID, reason: str) -> None:
        self.failed.append((jid, reason))


async def test_pdf_on_startup_populates_ctx() -> None:
    ctx: dict[str, Any] = {}
    await wpdf.on_startup(ctx)
    assert "settings" in ctx
    assert ctx["pytex_client"] is not None
    # Default-Settings → MinIO nicht konfiguriert → None.
    assert ctx["object_storage"] is None


def test_pdf_sessionmaker_default_and_injected() -> None:
    assert wpdf._sessionmaker({}) is not None
    sentinel = object()
    assert wpdf._sessionmaker({"pdf_sessionmaker": sentinel}) is sentinel


def test_pdf_pipeline_builds_with_ctx_deps() -> None:
    captured: dict[str, Any] = {}

    class _RP:
        def __init__(self, *, sessionmaker: Any, pytex: Any, storage: Any) -> None:
            captured["sessionmaker"] = sessionmaker
            captured["pytex"] = pytex
            captured["storage"] = storage

    import worker.pdf as mod

    orig = mod.RenderPipeline
    mod.RenderPipeline = _RP  # type: ignore[misc]
    try:
        pytex = object()
        storage = object()
        sm = object()
        mod._pipeline({"pytex_client": pytex, "object_storage": storage, "pdf_sessionmaker": sm})
    finally:
        mod.RenderPipeline = orig  # type: ignore[misc]
    assert captured["pytex"] is pytex
    assert captured["storage"] is storage


async def test_render_pdf_success(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _Pipeline(result="done")
    monkeypatch.setattr(wpdf, "_pipeline", lambda _ctx: pipeline)
    ctx = {"settings": SETTINGS}
    assert await wpdf.render_pdf(ctx, str(uuid4())) == "done"


async def test_render_pdf_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _Pipeline(error=RenderRetry("pytex 503"))
    monkeypatch.setattr(wpdf, "_pipeline", lambda _ctx: pipeline)
    ctx = {
        "settings": load_settings(pdf_max_tries=4, pdf_retry_backoff_seconds=9),
        "job_try": 1,
    }
    with pytest.raises(Retry) as ei:
        await wpdf.render_pdf(ctx, str(uuid4()))
    assert ei.value.defer_score == 9_000  # job_try(1) * backoff(9s), in ms
    assert pipeline.failed == []


async def test_render_pdf_dead_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _Pipeline(error=RenderRetry("pytex 503"))
    monkeypatch.setattr(wpdf, "_pipeline", lambda _ctx: pipeline)
    jid = uuid4()
    ctx = {"settings": load_settings(pdf_max_tries=3), "job_try": 3}
    assert await wpdf.render_pdf(ctx, str(jid)) == "dead"
    assert pipeline.failed == [(jid, "render_unavailable")]


async def test_render_pdf_default_job_try(monkeypatch: pytest.MonkeyPatch) -> None:
    # job_try fehlt → Default 1 → Retry.
    pipeline = _Pipeline(error=RenderRetry("boom"))
    monkeypatch.setattr(wpdf, "_pipeline", lambda _ctx: pipeline)
    with pytest.raises(Retry):
        await wpdf.render_pdf({"settings": SETTINGS}, str(uuid4()))


# =========================================================================== #
# worker/retention.py
# =========================================================================== #
class _RetSession:
    """Retention-Session: scalar/scalars/execute über FIFO-Queues + commit-Zähler."""

    def __init__(
        self,
        *,
        scalars: list[list[Any]] | None = None,
        scalar: list[Any] | None = None,
        execute_rowcounts: list[int] | None = None,
    ) -> None:
        self._scalars = scalars or []
        self._scalar = scalar or []
        self._rowcounts = execute_rowcounts or []
        self.committed = 0
        self.audit_calls = 0

    async def scalar(self, _stmt: Any) -> Any:
        return self._scalar.pop(0) if self._scalar else None

    async def scalars(self, _stmt: Any) -> Any:
        items = self._scalars.pop(0) if self._scalars else []
        return SimpleNamespace(all=lambda: items)

    async def execute(self, _stmt: Any) -> Any:
        rc = self._rowcounts.pop(0) if self._rowcounts else 0
        return SimpleNamespace(rowcount=rc)

    async def commit(self) -> None:
        self.committed += 1


def test_retention_sessionmaker_default_and_injected() -> None:
    assert wret._sessionmaker({}) is not None
    sentinel = object()
    assert wret._sessionmaker({"retention_sessionmaker": sentinel}) is sentinel


def test_retention_now_tz_aware() -> None:
    assert wret._now().tzinfo is not None


async def test_due_application_ids_default_retention() -> None:
    ids = [uuid4(), uuid4()]
    # erster scalar = default_retention_months (None → 24-Fallback), dann scalars=IDs.
    session = _RetSession(scalar=[None], scalars=[ids])
    assert await wret._due_application_ids(_maker(session)) == ids


async def test_due_application_ids_explicit_retention() -> None:
    session = _RetSession(scalar=[12], scalars=[[]])
    assert await wret._due_application_ids(_maker(session)) == []


async def test_anonymize_due_success(monkeypatch: pytest.MonkeyPatch) -> None:
    app1, app2 = uuid4(), uuid4()
    monkeypatch.setattr(
        wret, "_due_application_ids", _fake_due_ids([app1, app2])
    )
    anon_calls: list[uuid.UUID] = []

    class _AppSvc:
        def __init__(self, _session: Any) -> None: ...

        async def anonymize(self, app_id: uuid.UUID, **_kw: Any) -> None:
            anon_calls.append(app_id)

    audit_calls: list[str] = []

    async def _fake_audit(_session: Any, **kw: Any) -> None:
        audit_calls.append(kw["target_id"])

    monkeypatch.setattr(wret, "ApplicationsService", _AppSvc)
    monkeypatch.setattr(wret, "FilesService", lambda *_a, **_k: object())
    monkeypatch.setattr(wret, "audit_record", _fake_audit)

    sessions = [_RetSession(), _RetSession()]
    it = iter(sessions)
    maker = lambda: _SessionCM(next(it))  # noqa: E731
    count = await wret._anonymize_due(cast("Any", maker), storage=None)
    assert count == 2
    assert anon_calls == [app1, app2]
    assert audit_calls == [str(app1), str(app2)]
    assert all(s.committed == 1 for s in sessions)


async def test_anonymize_due_isolates_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    bad, good = uuid4(), uuid4()
    monkeypatch.setattr(wret, "_due_application_ids", _fake_due_ids([bad, good]))

    class _AppSvc:
        def __init__(self, _session: Any) -> None: ...

        async def anonymize(self, app_id: uuid.UUID, **_kw: Any) -> None:
            if app_id == bad:
                raise RuntimeError("anonymize broke")

    async def _fake_audit(_session: Any, **_kw: Any) -> None: ...

    monkeypatch.setattr(wret, "ApplicationsService", _AppSvc)
    monkeypatch.setattr(wret, "FilesService", lambda *_a, **_k: object())
    monkeypatch.setattr(wret, "audit_record", _fake_audit)

    sessions = [_RetSession(), _RetSession()]
    it = iter(sessions)
    maker = lambda: _SessionCM(next(it))  # noqa: E731
    # Die kaputte Zeile wird geloggt+übersprungen, die gute trotzdem committet.
    assert await wret._anonymize_due(cast("Any", maker), storage=None) == 1


async def test_anonymize_due_no_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wret, "_due_application_ids", _fake_due_ids([]))
    assert await wret._anonymize_due(_maker(_RetSession()), storage=None) == 0


async def test_purge_expired_counts_rows() -> None:
    session = _RetSession(execute_rowcounts=[3, 5])
    sessions_purged, links_purged = await wret._purge_expired(_maker(session), NOW)
    assert (sessions_purged, links_purged) == (3, 5)
    assert session.committed == 1


async def test_purge_expired_none_rowcount() -> None:
    # rowcount None → 0 (die ``or 0``-Zweige).
    session = _RetSession()

    async def _exec(_stmt: Any) -> Any:
        return SimpleNamespace(rowcount=None)

    session.execute = _exec  # type: ignore[method-assign]
    assert await wret._purge_expired(_maker(session), NOW) == (0, 0)


async def test_process_retention_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_anon(_maker: Any, _storage: Any) -> int:
        return 2

    async def _fake_purge(_maker: Any, _now: Any) -> tuple[int, int]:
        return 4, 6

    monkeypatch.setattr(wret, "_anonymize_due", _fake_anon)
    monkeypatch.setattr(wret, "_purge_expired", _fake_purge)
    monkeypatch.setattr(wret, "build_object_storage", lambda _s: None)
    out = await wret.process_retention({"settings": SETTINGS})
    assert out == "anonymized=2 sessions_purged=4 links_purged=6"


async def test_process_retention_loads_settings_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_anon(_maker: Any, _storage: Any) -> int:
        return 0

    async def _fake_purge(_maker: Any, _now: Any) -> tuple[int, int]:
        return 0, 0

    monkeypatch.setattr(wret, "_anonymize_due", _fake_anon)
    monkeypatch.setattr(wret, "_purge_expired", _fake_purge)
    monkeypatch.setattr(wret, "build_object_storage", lambda _s: None)
    monkeypatch.setattr(wret, "load_settings", lambda: SETTINGS)
    # ctx ohne 'settings' → load_settings()-Pfad.
    out = await wret.process_retention({})
    assert out == "anonymized=0 sessions_purged=0 links_purged=0"


def _fake_due_ids(ids: list[uuid.UUID]) -> Any:
    async def _impl(_maker: Any) -> list[uuid.UUID]:
        return ids

    return _impl


# =========================================================================== #
# worker/main.py  — _on_startup-Orchestrierung
# =========================================================================== #
async def test_main_on_startup_calls_all_inits(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    async def _mk(name: str) -> Any:
        async def _impl(_ctx: dict[str, Any]) -> None:
            called.append(name)

        return _impl

    monkeypatch.setattr(wmain, "mail_on_startup", await _mk("mail"))
    monkeypatch.setattr(wmain, "scan_on_startup", await _mk("scan"))
    monkeypatch.setattr(wmain, "pdf_on_startup", await _mk("pdf"))
    monkeypatch.setattr(wmain, "webhook_on_startup", await _mk("webhook"))
    monkeypatch.setattr(wmain, "deadlines_on_startup", await _mk("deadlines"))
    await wmain._on_startup({})
    assert called == ["mail", "scan", "pdf", "webhook", "deadlines"]


# =========================================================================== #
# worker/deadlines.py — Restdeckung: discard-Log + Auto-Transitionen
# =========================================================================== #
class _DlSession:
    """``execute`` liefert gequeuete Ergebnisse als scalars().all()."""

    def __init__(self, results: list[list[Any]], *, rowcount: int = 0) -> None:
        self._results = list(results)
        self._rowcount = rowcount
        self.committed = 0

    async def execute(self, _stmt: Any) -> Any:
        items = self._results.pop(0) if self._results else []
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: items),
            rowcount=self._rowcount,
        )

    async def commit(self) -> None:
        self.committed += 1


def _dl_maker(sessions: list[Any]) -> Any:
    it = iter(sessions)
    return lambda: _SessionCM(next(it))


@freeze_time("2026-06-16 12:00:00")
async def test_discard_unconfirmed_logs_when_rows_deleted() -> None:
    session = _DlSession([], rowcount=2)
    ctx = {"settings": SETTINGS, "deadlines_sessionmaker": _maker(session)}
    assert await wd._discard_unconfirmed(ctx, NOW) == 2
    assert session.committed == 1


@freeze_time("2026-06-16 12:00:00")
async def test_discard_unconfirmed_none_rowcount() -> None:
    session = _DlSession([])

    async def _exec(_stmt: Any) -> Any:
        return SimpleNamespace(rowcount=None)

    session.execute = _exec  # type: ignore[method-assign]
    ctx = {"settings": SETTINGS, "deadlines_sessionmaker": _maker(session)}
    assert await wd._discard_unconfirmed(ctx, NOW) == 0


@pytest.fixture
def _patched_auto(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(wd, "build_notify_dispatcher", lambda _pool: object())
    yield


async def test_auto_transitions_advances(
    _patched_auto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    app1, app2 = uuid4(), uuid4()

    class _Flow:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def auto_advance(self, app_id: uuid.UUID, _principal: Any) -> Any:
            return SimpleNamespace() if app_id == app1 else None

    monkeypatch.setattr(wd, "FlowService", _Flow)
    scan = _DlSession([[app1, app2]])
    # 1 scan-Session + 2 per-App-Sessions.
    sessions = [scan, _DlSession([]), _DlSession([])]
    ctx = {"settings": SETTINGS, "deadlines_sessionmaker": _dl_maker(sessions)}
    # app1 advanced (1), app2 None (0) → advanced == 1.
    assert await wd._process_auto_transitions(ctx) == 1


async def test_auto_transitions_conflict_skipped(
    _patched_auto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    app1 = uuid4()

    class _Flow:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def auto_advance(self, _app_id: uuid.UUID, _principal: Any) -> Any:
            raise ConflictError("guard", code="conflict")

    monkeypatch.setattr(wd, "FlowService", _Flow)
    sessions = [_DlSession([[app1]]), _DlSession([])]
    ctx = {"settings": SETTINGS, "deadlines_sessionmaker": _dl_maker(sessions)}
    assert await wd._process_auto_transitions(ctx) == 0


async def test_auto_transitions_notfound_skipped(
    _patched_auto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    app1 = uuid4()

    class _Flow:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def auto_advance(self, _app_id: uuid.UUID, _principal: Any) -> Any:
            raise NotFoundError("app gone")

    monkeypatch.setattr(wd, "FlowService", _Flow)
    sessions = [_DlSession([[app1]]), _DlSession([])]
    ctx = {"settings": SETTINGS, "deadlines_sessionmaker": _dl_maker(sessions)}
    assert await wd._process_auto_transitions(ctx) == 0


async def test_auto_transitions_generic_error_isolated(
    _patched_auto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad, good = uuid4(), uuid4()

    class _Flow:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def auto_advance(self, app_id: uuid.UUID, _principal: Any) -> Any:
            if app_id == bad:
                raise RuntimeError("boom")
            return SimpleNamespace()

    monkeypatch.setattr(wd, "FlowService", _Flow)
    sessions = [_DlSession([[bad, good]]), _DlSession([]), _DlSession([])]
    ctx = {"settings": SETTINGS, "deadlines_sessionmaker": _dl_maker(sessions)}
    # bad geloggt+übersprungen, good advanced → 1.
    assert await wd._process_auto_transitions(ctx) == 1


# =========================================================================== #
# worker/task_reminders.py — Rand-Branches
# =========================================================================== #
def _config(
    *, enabled: bool = True, after_days: int = 5, repeat_days: int = 7
) -> NotificationSettings:
    return NotificationSettings(
        id=1,
        task_reminder_enabled=enabled,
        task_reminder_after_days=after_days,
        task_reminder_repeat_days=repeat_days,
    )


def _state(kind: str = "normal", label_i18n: Any = None) -> Any:
    from app.modules.flow.models import State

    return State(
        id=uuid.uuid4(),
        flow_version_id=uuid.uuid4(),
        key="review",
        label_i18n={"de": "Prüfung"} if label_i18n is None else label_i18n,
        kind=kind,
        config={},
    )


def _tr_ctx(session: Any, queue: FakeQueue) -> dict[str, Any]:
    return {"sessionmaker": _maker(session), "mail_queue": queue, "settings": SETTINGS}


@pytest.fixture
def _patch_recipients(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def fake_actionable(_session: Any, *, state: Any, gremium_id: Any) -> list[str]:
        return ["team@x.de"]

    monkeypatch.setattr(wtr, "actionable_principal_emails", fake_actionable)
    yield


def test_tr_sessionmaker_default_and_injected() -> None:
    # Default-Pfad (Import des globalen get_sessionmaker) muss greifen.
    assert wtr._sessionmaker({}) is not None
    sentinel = object()
    assert wtr._sessionmaker({"sessionmaker": sentinel}) is sentinel


def test_tr_mail_queue_default_and_injected() -> None:
    sentinel = object()
    assert wtr._mail_queue({"mail_queue": sentinel}) is sentinel
    # ohne mail_queue → mail_queue_from_pool(None) → None.
    assert wtr._mail_queue({}) is None


async def test_tr_disabled_returns_zero(_patch_recipients: None) -> None:
    session = NotifFakeSession()
    session.add(_config(enabled=False))
    queue = FakeQueue()
    assert await process_reminders_disabled(session, queue) == 0


async def process_reminders_disabled(session: Any, queue: FakeQueue) -> int:
    return await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW)


async def test_tr_no_due_rows_returns_zero(_patch_recipients: None) -> None:
    # _due_applications: executes=[] → rows leer → frühe Rückgabe (Zeile 144).
    session = NotifFakeSession(executes=[[]])
    session.add(_config())
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 0


async def test_tr_state_none_or_not_actionable_skipped(_patch_recipients: None) -> None:
    # State-Lookup liefert nichts → state is None → continue (Zeile 171).
    app_id = uuid.uuid4()
    state = _state()
    session = NotifFakeSession(
        executes=[[(app_id, state.id, NOW - timedelta(days=6))]],
        scalars=[[], []],  # keine States, keine Logs
    )
    session.add(_config())
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 0
    assert queue.messages == []


async def test_tr_not_actionable_state_skipped(_patch_recipients: None) -> None:
    # normal-State ohne handlungsfähige Übergänge (count=0) → state_actionable False.
    app_id = uuid.uuid4()
    state = _state()
    session = NotifFakeSession(
        executes=[[(app_id, state.id, NOW - timedelta(days=6))]],
        scalars=[[state], []],
        scalar=[0],  # state_actionable: 0 manuelle Übergänge
    )
    session.add(_config())
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 0


async def test_tr_remind_one_app_missing(_patch_recipients: None) -> None:
    # _remind_one: app_row None → False (Zeile 209). Wird über die Schleife ausgelöst.
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    session = NotifFakeSession(
        executes=[
            [(app_id, state.id, NOW - timedelta(days=6))],  # due-Kandidaten
            [],  # _remind_one: Antrag fehlt → first()=None
        ],
        scalars=[[state], []],
        scalar=[1, event_id],
    )
    session.add(_config())
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 0


async def test_tr_remind_one_no_recipients(monkeypatch: pytest.MonkeyPatch) -> None:
    # actionable_principal_emails liefert [] → _remind_one False (Zeile 215).
    async def empty(_s: Any, *, state: Any, gremium_id: Any) -> list[str]:
        return []

    monkeypatch.setattr(wtr, "actionable_principal_emails", empty)
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    session = NotifFakeSession(
        executes=[
            [(app_id, state.id, NOW - timedelta(days=6))],
            [({"title": "X"}, None)],  # Antrag (data, gremium_id)
        ],
        scalars=[[state], []],
        scalar=[1, event_id],
    )
    session.add(_config())
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 0


async def test_tr_label_fallback_other_lang(_patch_recipients: None) -> None:
    # label_i18n ohne mail_default_lang-Key → next(iter(values())) (Zeile 218->219 else-Zweig).
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state(label_i18n={"fr": "Examen"})
    session = NotifFakeSession(
        executes=[
            [(app_id, state.id, NOW - timedelta(days=6))],
            [({"title": "Beamer"}, None)],
        ],
        scalars=[[state], [], [], []],
        scalar=[1, event_id],
    )
    session.add(_config())
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 1
    assert "Examen" in queue.messages[0].text or "Beamer" in queue.messages[0].subject


async def test_tr_empty_label_i18n_no_status(_patch_recipients: None) -> None:
    # label_i18n leer/kein dict → status_label bleibt "" (Bedingung false, Zeile 218).
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state(label_i18n={})
    session = NotifFakeSession(
        executes=[
            [(app_id, state.id, NOW - timedelta(days=6))],
            [({"title": "Beamer"}, None)],
        ],
        scalars=[[state], [], [], []],
        scalar=[1, event_id],
    )
    session.add(_config())
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 1


async def test_tr_non_string_title(_patch_recipients: None) -> None:
    # title kein str → applicationTitle "" (Zeile 230 else).
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    session = NotifFakeSession(
        executes=[
            [(app_id, state.id, NOW - timedelta(days=6))],
            [({"title": 123}, None)],
        ],
        scalars=[[state], [], [], []],
        scalar=[1, event_id],
    )
    session.add(_config())
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 1


async def test_tr_per_app_failure_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    # _remind_one wirft → Loop fängt ab (Zeilen 103-104), Zyklus läuft weiter.
    async def boom(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("remind broke")

    async def fake_actionable(_s: Any, *, state: Any, gremium_id: Any) -> list[str]:
        return ["team@x.de"]

    monkeypatch.setattr(wtr, "actionable_principal_emails", fake_actionable)
    monkeypatch.setattr(wtr, "_remind_one", boom)
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    session = NotifFakeSession(
        executes=[[(app_id, state.id, NOW - timedelta(days=6))]],
        scalars=[[state], []],
        scalar=[1, event_id],
    )
    session.add(_config())
    queue = FakeQueue()
    # Trotz Fehler kein Crash, sent == 0.
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 0


async def test_tr_loads_settings_and_default_now(monkeypatch: pytest.MonkeyPatch) -> None:
    # ctx ohne settings + now=None → load_settings() + datetime.now(UTC)-Pfade.
    monkeypatch.setattr(wtr, "load_settings", lambda: SETTINGS)

    async def empty(_s: Any, *, state: Any, gremium_id: Any) -> list[str]:
        return []

    monkeypatch.setattr(wtr, "actionable_principal_emails", empty)
    session = NotifFakeSession(executes=[[]])
    session.add(_config(enabled=False))
    queue = FakeQueue()
    ctx = {"sessionmaker": _maker(session), "mail_queue": queue}
    assert await wtr.process_task_reminders(ctx) == 0


async def test_tr_once_mode_skips_already_reminded(_patch_recipients: None) -> None:
    # Einmal-Modus (repeat_days=0): bereits für diesen status_event erinnert →
    # continue (Zeile 185), kein erneuter Versand.
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    log = TaskReminderLog(
        application_id=app_id,
        status_event_id=event_id,
        reminded_at=NOW - timedelta(days=30),
    )
    session = NotifFakeSession(
        executes=[[(app_id, state.id, NOW - timedelta(days=40))]],
        scalars=[[state], [log]],
        scalar=[1, event_id],
    )
    session.add(_config(repeat_days=0))
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 0
    assert queue.messages == []


async def test_tr_repeat_mode_updates_existing_log(_patch_recipients: None) -> None:
    # Wiederhol-Modus mit abgelaufenem Intervall → erneut erinnern; vorhandenes Log
    # wird fortgeschrieben statt neu angelegt (Zeilen 253-254 else-Zweig).
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    log = TaskReminderLog(
        application_id=app_id,
        status_event_id=event_id,
        reminded_at=NOW - timedelta(days=8),
    )
    session = NotifFakeSession(
        executes=[
            [(app_id, state.id, NOW - timedelta(days=20))],
            [({"title": "Beamer"}, None)],
        ],
        scalars=[[state], [log], [], []],
        scalar=[1, event_id],
    )
    session.store[app_id] = log  # session.get(TaskReminderLog, app_id) findet das Log
    session.add(_config(repeat_days=7))
    queue = FakeQueue()
    assert await wtr.process_task_reminders(_tr_ctx(session, queue), now=NOW) == 1
    assert log.reminded_at == NOW  # fortgeschrieben, keine zweite Zeile


def test_naive_utc_strips_and_keeps() -> None:
    aware = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    naive = wtr._naive_utc(aware)
    assert naive.tzinfo is None
    already = datetime(2026, 6, 16, 12, 0)
    assert wtr._naive_utc(already) is already
