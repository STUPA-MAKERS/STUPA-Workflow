"""Shared fixtures: a TestClient and a fake render backend.

Unit tests never touch tectonic. They monkeypatch `app.render_blob_async`, so a
test drives the wrapper logic in isolation: parsing, error mapping and response
shaping. The fake records the `BuildRequest` it received. A test can then assert
that the wrapper forwards the body, the variant and the kinds unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from pytex_api import BuildRequest, BuildResult, OutputKind

import app as app_module


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_module.app) as c:
        yield c


class RenderRecorder:
    """Capture the last `BuildRequest` and replay a canned result or error."""

    def __init__(self) -> None:
        self.calls: list[BuildRequest] = []
        self._result: BuildResult | None = None
        self._error: Exception | None = None

    @property
    def last(self) -> BuildRequest:
        return self.calls[-1]

    def returns(self, result: BuildResult) -> None:
        self._result = result
        self._error = None

    def raises(self, error: Exception) -> None:
        self._error = error
        self._result = None

    async def __call__(self, req: BuildRequest) -> BuildResult:
        self.calls.append(req)
        if self._error is not None:
            raise self._error
        assert self._result is not None, "RenderRecorder: set returns()/raises() first"
        return self._result


def make_result(
    output: bytes = b"%PDF-1.5 fake pdf",
    output_kind: OutputKind = OutputKind.PDF,
    *,
    warnings: tuple[str, ...] = (),
    duration_s: float = 0.123,
) -> BuildResult:
    return BuildResult(
        output=output,
        output_kind=output_kind,
        log="render log",
        warnings=warnings,
        duration_s=duration_s,
    )


@pytest.fixture
def render(monkeypatch: pytest.MonkeyPatch) -> RenderRecorder:
    rec = RenderRecorder()
    monkeypatch.setattr(app_module, "render_blob_async", rec)
    return rec


@pytest.fixture
def make_pdf_result() -> Callable[..., BuildResult]:
    return make_result
