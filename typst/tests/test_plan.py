"""The plan variant: the data of a Haushaltsplan and its layout (§F/finance/budget/000875)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from typst_service.compiler import default_compiler
from typst_service.document import build_document
from typst_service.markdown import ConversionError

SOURCE = '---\ntitle: "Haushaltsplan"\n---\n'
HEADERS = ["Schlüssel", "Bezeichnung", "Ansatz 2026", "Vermerke", "Gesperrt", "Erläuterung"]


def _row(kind: str, name: str, amount: str = "", depth: int = 0) -> dict[str, object]:
    return {"kind": kind, "depth": depth, "cells": ["", name, amount, "", "", ""]}


def _plan(**changes: object) -> dict[str, object]:
    return {
        "plan": {
            "title": "Haushaltsplan VS-Mittel 2026",
            "mark": "Entwurf",
            "head": [["Haushalt", "VS-Mittel"], ["Stand", "Entwurf"]],
            "headers": HEADERS,
            "money": [2, 4],
            "rows": [
                _row("group", "Ausgaben"),
                _row("line", "Personalausgaben", "64.000,00"),
                _row("line", "Büro und IT", "14.000,00", depth=1),
                _row("sum", "Summe Ausgaben", "64.000,00"),
                _row("balance", "Saldo", "−64.000,00"),
            ],
            **changes,
        }
    }


def test_the_plan_variant_builds_the_plan_layout() -> None:
    """The variant reads the `plan` config key and takes the StuPa logo as default."""
    doc = build_document(SOURCE, variant="plan", config=_plan())
    plan = doc["plan"]
    assert doc["layout"] == "plan"
    assert doc["logos"] == [{"name": "STUPA"}]
    assert doc["footer_logos"] == []
    assert isinstance(plan, dict)
    assert plan["mark"] == "Entwurf"
    assert plan["headers"] == HEADERS
    assert len(plan["rows"]) == 5


def test_the_plan_takes_its_title_from_the_source_and_its_logos_from_the_config() -> None:
    """Without a title in the config the frontmatter names the plan."""
    config = {**_plan(title="", mark=None), "logos": ["ASTA"], "footer_logos": "HSRT"}
    doc = build_document(SOURCE, variant="plan", config=config)
    plan = doc["plan"]
    assert isinstance(plan, dict)
    assert plan["title"] == "Haushaltsplan"
    assert plan["mark"] == ""
    assert doc["logos"] == [{"name": "ASTA"}]
    assert doc["footer_logos"] == [{"name": "HSRT"}]


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"plan": "x"},
        _plan(headers=["one"]),
        _plan(headers="x"),
        _plan(rows="x"),
        _plan(head="x"),
        _plan(head=[["only a label"]]),
        _plan(money=["2"]),
        _plan(money=None),
        _plan(rows=[_row("other", "x")]),
        _plan(rows=["x"]),
        _plan(rows=[{"kind": "line", "depth": "0", "cells": ["", "", "", "", "", ""]}]),
        _plan(rows=[{"kind": "line", "depth": 0, "cells": ["too", "few"]}]),
        _plan(rows=[{"kind": "line", "depth": 0, "cells": [1, 2, 3, 4, 5, 6]}]),
    ],
)
def test_a_plan_of_a_wrong_shape_is_refused(config: dict[str, object]) -> None:
    """A config that is no plan gives a conversion error, so the service answers 400."""
    with pytest.raises(ConversionError):
        build_document(SOURCE, variant="plan", config=config)


def test_an_unknown_variant_names_the_plan_variant() -> None:
    """The error for an unknown variant lists `plan` with the protocol variants."""
    with pytest.raises(ConversionError, match="plan"):
        build_document(SOURCE, variant="nope")


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("typst") is None or shutil.which("pdftotext") is None,
    reason="needs the typst CLI and poppler (nix develop .#typst)",
)
def test_the_plan_renders_landscape_with_its_mark_on_each_page(tmp_path: Path) -> None:
    """A long plan breaks across pages: each page is A4 landscape and names the state."""
    lines = [_row("line", f"Titel {n}", "1.000,00") for n in range(120)]
    rows = [_row("group", "Ausgaben"), *lines, _row("sum", "Summe Ausgaben", "120.000,00")]
    doc = build_document(SOURCE, variant="plan", config=_plan(rows=rows))
    pdf = asyncio.run(default_compiler().compile(doc, {}))
    path = tmp_path / "plan.pdf"
    path.write_bytes(pdf)
    info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, check=True)
    pages = int(next(line.split()[1] for line in info.stdout.splitlines() if "Pages" in line))
    size = next(line for line in info.stdout.splitlines() if line.startswith("Page size"))
    assert pages > 1
    assert "841.89 x 595.2" in size
    assert b"pdfuaid:part" in pdf
    texts = [
        subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for page in range(1, pages + 1)
    ]
    assert all("ENTWURF" in text and "Bezeichnung" in text for text in texts)
    assert "Summe Ausgaben" in texts[-1]
