"""Opt-in real-render tests (no mock). Enabled with RUN_PYTEX_INTEGRATION=1.

The md->tex path exercises the genuine pytex v1.0.0 variant machinery without
needing tectonic (no PDF compile). The md->pdf path additionally needs a working
tectonic and a warm bundle cache, so it is skipped unless one is on PATH.
"""

from __future__ import annotations

import os
import shutil

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

_ENABLED = os.environ.get("RUN_PYTEX_INTEGRATION") == "1"
skip_unless_enabled = pytest.mark.skipif(
    not _ENABLED, reason="set RUN_PYTEX_INTEGRATION=1 to run real-render tests"
)

PLAIN_MD = b"# Title\n\nA paragraph.\n"


@skip_unless_enabled
@pytest.mark.parametrize("variant", ["report", "protocol-stupa", "protocol-asta"])
def test_real_md_to_tex_per_variant(client: TestClient, variant: str) -> None:
    resp = client.post(
        f"/render?input_kind=md&output_kind=tex&variant={variant}",
        content=PLAIN_MD,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    assert "\\documentclass" in resp.text
    assert "\\begin{document}" in resp.text


@skip_unless_enabled
def test_real_md_to_tex_frontmatter_autodetects_protocol(client: TestClient) -> None:
    md = b"---\ntyp: protokoll\ngremium: StuPa\n---\n# Sitzung\n\nTOP 1.\n"
    resp = client.post("/render?input_kind=md&output_kind=tex", content=md)
    assert resp.status_code == 200, resp.text
    assert "\\documentclass" in resp.text


@skip_unless_enabled
@pytest.mark.skipif(
    shutil.which("tectonic") is None, reason="tectonic not installed"
)
def test_real_md_to_pdf(client: TestClient) -> None:
    resp = client.post(
        "/render?input_kind=md&output_kind=pdf&trust_level=trusted",
        content=PLAIN_MD,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
