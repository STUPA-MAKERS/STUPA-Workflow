"""E2E contract: TypstClient against the **real** typst container.

The test renders a small protocol through ``POST /render`` and expects real PDF
bytes. It skips when no container runs at ``TYPST_URL``, which is the local case
without the stack. The E2E stage (compose) has the typst service, so the test
applies there. The respx mock path (``test_pdf_typst_client``) already covers the
client logic as a unit test.
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.modules.pdf.typst_client import TypstClient, TypstError

pytestmark = pytest.mark.e2e

_MARKDOWN = """---
title: "Contract"
typ: protokoll
gremium: "stupa"
---

# Contract

> [!abstimmung] **Frage**
> ja: 3, nein: 1, enthaltung: 0
"""


async def _reachable(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(url.rstrip("/") + "/health")
            return r.status_code == httpx.codes.OK
    except httpx.HTTPError:
        return False


async def test_render_real_typst_returns_pdf() -> None:
    url = os.environ.get("TYPST_URL", "http://localhost:8099")
    if not await _reachable(url):
        pytest.skip(f"no typst container at {url}")
    client = TypstClient(base_url=url, timeout_seconds=60)
    try:
        pdf = await client.render_pdf(_MARKDOWN, variant="protocol-stupa")
    except TypstError as exc:  # pragma: no cover - container build problem
        pytest.fail(f"typst render failed: {exc}")
    assert pdf.startswith(b"%PDF")
