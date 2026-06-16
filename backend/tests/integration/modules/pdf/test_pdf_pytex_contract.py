"""E2E-Contract: PytexClient gegen den **echten** pytex-Container (T-20 Akzeptanz).

Rendert ein kleines Markdown über ``POST /render`` und erwartet echte PDF-Bytes. Wird
übersprungen, wenn unter ``PYTEX_URL`` kein Container läuft (lokal ohne Stack); die
E2E-Stage (T-04, Compose) hat pytex → der Test greift. Der respx-Mock-Pfad
(``test_pdf_pytex_client``) deckt die Client-Logik bereits unit-seitig ab.
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
