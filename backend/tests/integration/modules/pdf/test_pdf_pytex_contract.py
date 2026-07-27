"""E2E contract: PytexClient against the **real** pytex container (T-20 acceptance).

The test renders a small Markdown document through ``POST /render`` and expects real
PDF bytes. It skips when no container runs at ``PYTEX_URL``, which is the local case
without the stack. The E2E stage (T-04, compose) has pytex, so the test applies there.
The respx mock path (``test_pdf_pytex_client``) already covers the client logic as a
unit test.
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.modules.pdf.pytex_client import PytexClient, PytexError

pytestmark = pytest.mark.e2e

_MARKDOWN = """---
title: "T-20 Contract"
typ: antrag
gremium: "stupa"
---

# T-20 Contract

- **Feld:** Wert
"""


async def _reachable(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(url.rstrip("/") + "/health")
            return r.status_code == httpx.codes.OK
    except httpx.HTTPError:
        return False


async def test_render_real_pytex_returns_pdf() -> None:
    url = os.environ.get("PYTEX_URL", "http://localhost:8099")
    if not await _reachable(url):
        pytest.skip(f"kein pytex-Container unter {url}")
    client = PytexClient(base_url=url, trust_level="trusted", timeout_seconds=180)
    try:
        pdf = await client.render_pdf(_MARKDOWN, variant="report")
    except PytexError as exc:  # pragma: no cover - Container-Build-Problem
        pytest.fail(f"pytex render failed: {exc}")
    assert pdf.startswith(b"%PDF")
