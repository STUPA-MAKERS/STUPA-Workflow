"""The corporate design of a Gremium must reach the renderer.

The resolver and the CRUD around it are covered elsewhere. These tests cover
`cd_render_config`: what a resolved design turns into as pytex `config`, and what an
empty slot must NOT turn into.

The end-to-end seam — config and assets actually reaching pytex, and the design never
deciding the document shape — is pinned on the protocol render in
`tests/unit/modules/protocol/test_protocol_service.py`.
"""

from __future__ import annotations

from typing import Any

from app.modules.admin.cd_resolver import ResolvedCdVariant, cd_render_config


def _resolved(**over: Any) -> ResolvedCdVariant:
    base: dict[str, Any] = {
        "base_variant": "protocol",
        "title_logos": ("STUPA", "brand.png"),
        "footer_logos": ("brand.png",),
        "assets": {"brand.png": b"\x89PNG\r\n\x1a\n"},
    }
    base.update(over)
    return ResolvedCdVariant(**base)


def test_an_empty_logo_slot_stays_out_of_the_config() -> None:
    """An empty list would override the default of the shape with nothing."""
    config = cd_render_config(_resolved(footer_logos=()))

    assert config == {"logos": ["STUPA", "brand.png"]}
    assert "footer_logos" not in config


def test_a_design_without_any_logo_gives_an_empty_config() -> None:
    assert cd_render_config(_resolved(title_logos=(), footer_logos=())) == {}
