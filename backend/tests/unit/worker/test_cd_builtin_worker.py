"""The worker job `migrate_builtin_cd_logos` and its start-up enqueue."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from arq import Retry

from app.modules.admin.cd_builtin.convert import BuiltinConversion
from app.modules.files.storage import StorageError
from app.shared.errors import ServiceUnavailableError
from worker import cd_builtin
from worker.cd_builtin import JOB_NAME, migrate_builtin_cd_logos, on_startup
from worker.main import WorkerSettings


def _maker() -> Any:
    @asynccontextmanager
    async def _session() -> AsyncIterator[object]:
        yield object()

    return _session


def _ctx(**kw: Any) -> dict[str, Any]:
    return {"cd_builtin_sessionmaker": _maker(), "object_storage": "storage", **kw}


def _fake_convert(result: BuiltinConversion | Exception) -> Any:
    calls: list[Any] = []

    async def convert(session: object, storage: object) -> BuiltinConversion:
        calls.append(storage)
        if isinstance(result, Exception):
            raise result
        return result

    convert.calls = calls  # type: ignore[attr-defined]
    return convert


async def test_job_reports_the_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    convert = _fake_convert(BuiltinConversion(logos=9, variants=5, renamed=1))
    monkeypatch.setattr(cd_builtin, "convert_builtin_cd_logos", convert)
    out = await migrate_builtin_cd_logos(_ctx())
    assert out == "converted 9 logos in 5 variants, renamed 1"
    assert convert.calls == ["storage"]


async def test_job_reports_busy_when_another_runner_holds_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cd_builtin, "convert_builtin_cd_logos", _fake_convert(BuiltinConversion(skipped=True))
    )
    assert await migrate_builtin_cd_logos(_ctx()) == "busy"


@pytest.mark.parametrize("error", [StorageError("down"), ServiceUnavailableError("off")])
async def test_job_retries_a_storage_error(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(cd_builtin, "convert_builtin_cd_logos", _fake_convert(error))
    with pytest.raises(Retry):
        await migrate_builtin_cd_logos(_ctx(job_try=2))


async def test_job_gives_up_after_the_last_try(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cd_builtin, "convert_builtin_cd_logos", _fake_convert(StorageError("down"))
    )
    assert await migrate_builtin_cd_logos(_ctx(job_try=5)) == "failed"


def test_default_sessionmaker_is_the_app_one(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(cd_builtin, "get_sessionmaker", lambda: sentinel)
    assert cd_builtin._sessionmaker({}) is sentinel


class _Redis:
    def __init__(self) -> None:
        self.jobs: list[str] = []

    async def enqueue_job(self, name: str) -> None:
        self.jobs.append(name)


async def test_startup_enqueues_the_job() -> None:
    redis = _Redis()
    await on_startup({"redis": redis})
    assert redis.jobs == [JOB_NAME]


async def test_startup_without_redis_does_nothing() -> None:
    await on_startup({})


def test_worker_registers_the_job() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert JOB_NAME in names
