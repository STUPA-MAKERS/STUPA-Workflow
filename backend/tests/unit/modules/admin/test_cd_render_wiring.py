"""The corporate design of a Gremium must reach the renderer.

Covers the seam: a resolved design becomes the pytex `config` plus asset bytes,
and a Gremium without a design still renders.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.admin.cd_resolver import ResolvedCdVariant, cd_render_config
from app.modules.pdf import render as render_mod
from app.modules.pdf.models import RenderJob
from app.modules.pdf.render import RenderPipeline
from tests._support.files_fakes import FakeStorage
from tests._support.pdf_fakes import FakePdfSession, FakePytex, FakeSessionmaker

GREMIUM_ID = uuid.uuid4()


def _resolved(**over: Any) -> ResolvedCdVariant:
    base: dict[str, Any] = {
        "base_variant": "protocol",
        "title_logos": ("STUPA", "brand.png"),
        "footer_logos": ("brand.png",),
        "assets": {"brand.png": b"\x89PNG\r\n\x1a\n"},
    }
    base.update(over)
    return ResolvedCdVariant(**base)


class _DocStub:
    variant = "report"
    gremium_id = GREMIUM_ID


class _SvcStub:
    def __init__(self, _session: object) -> None: ...

    async def load_application_doc(self, _app_id: uuid.UUID) -> _DocStub:
        return _DocStub()


@pytest.fixture(autouse=True)
def _stub_doc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_mod, "PdfService", _SvcStub)
    monkeypatch.setattr(render_mod, "build_application_markdown", lambda _doc: "# md")


def _run(monkeypatch: pytest.MonkeyPatch, resolved: ResolvedCdVariant | None) -> FakePytex:
    async def _fake_resolve(*_args: object, **_kw: object) -> ResolvedCdVariant | None:
        return resolved

    monkeypatch.setattr(render_mod, "resolve_cd_variant", _fake_resolve)
    job = RenderJob(application_id=uuid.uuid4(), status="pending")
    job.id = uuid.uuid4()
    pytex = FakePytex()
    pipe = RenderPipeline(
        sessionmaker=FakeSessionmaker(FakePdfSession(store={job.id: job})),  # type: ignore[arg-type]
        pytex=pytex,  # type: ignore[arg-type]
        storage=FakeStorage(),  # type: ignore[arg-type]
    )
    import asyncio

    assert asyncio.run(pipe.run(job.id)) == "done"
    return pytex


def test_a_resolved_design_reaches_pytex_as_config_and_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytex = _run(monkeypatch, _resolved())

    # Shape comes from the document kind, not the design; the design adds logos.
    assert pytex.calls[0][1] == "report"
    assert pytex.configs[0] == {
        "logos": ["STUPA", "brand.png"],
        "footer_logos": ["brand.png"],
    }
    # Only the uploaded logo carries bytes. The vendored one ships with pytex.
    assert pytex.assets[0] == {"brand.png": b"\x89PNG\r\n\x1a\n"}


def test_without_a_design_the_render_keeps_the_variant_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytex = _run(monkeypatch, None)

    assert pytex.calls[0][1] == "report"
    assert pytex.configs[0] is None
    assert pytex.assets[0] is None


def test_an_empty_logo_slot_stays_out_of_the_config() -> None:
    """An empty list would override the default of the shape with nothing."""
    config = cd_render_config(_resolved(footer_logos=()))

    assert config == {"logos": ["STUPA", "brand.png"]}
    assert "footer_logos" not in config


def test_a_design_without_any_logo_gives_an_empty_config() -> None:
    assert cd_render_config(_resolved(title_logos=(), footer_logos=())) == {}
