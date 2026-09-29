"""Shared fixtures: a TestClient and a fake compiler.

The HTTP tests never run typst. They swap `app._compiler` for a recorder that
keeps the document tree and the assets it received, so a test can assert on
the forwarding contract and the error mapping in isolation.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typst_service import app as app_module

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_PDF = b"%PDF-1.7 fake pdf"


class CompileRecorder:
    """Capture each compile call and replay a canned PDF or error."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], dict[str, bytes]]] = []
        self.error: Exception | None = None

    @property
    def doc(self) -> dict[str, object]:
        return self.calls[-1][0]

    @property
    def assets(self) -> dict[str, bytes]:
        return self.calls[-1][1]

    async def compile(self, doc: dict[str, object], assets: dict[str, bytes]) -> bytes:
        self.calls.append((doc, assets))
        if self.error is not None:
            raise self.error
        return FAKE_PDF


@pytest.fixture
def compiler(monkeypatch: pytest.MonkeyPatch) -> CompileRecorder:
    recorder = CompileRecorder()
    monkeypatch.setattr(app_module, "_compiler", recorder)
    return recorder


@pytest.fixture
def client(compiler: CompileRecorder) -> Iterator[TestClient]:
    with TestClient(app_module.app) as c:
        yield c
