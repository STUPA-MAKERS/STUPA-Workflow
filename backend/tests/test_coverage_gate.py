"""Negativ-Probe für das kritische Coverage-Gate (Akzeptanzkriterium T-04).

Beweist, dass das Gate aus `scripts.coverage_critical` bei < 100 % Branch eines
kritischen Moduls *blockiert* (Exit 1) und bei 100 % bzw. fehlendem Modul *durchlässt*.
"""

from __future__ import annotations

from pathlib import Path

from scripts.coverage_critical import check, main, parse_classes

MODULES = ["app/modules/auth", "app/modules/voting"]


def _write_xml(tmp_path: Path, entries: dict[str, float]) -> Path:
    classes = "".join(
        f'<class filename="{name}" branch-rate="{rate}" line-rate="1"/>'
        for name, rate in entries.items()
    )
    xml = (
        '<?xml version="1.0" ?><coverage><packages><package><classes>'
        f"{classes}"
        "</classes></package></packages></coverage>"
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "coverage.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def test_blocks_when_critical_module_below_100(tmp_path: Path) -> None:
    classes = parse_classes(_write_xml(tmp_path, {"app/modules/auth/service.py": 0.5}))
    failures = check(classes, MODULES, 1.0)
    assert failures
    assert "app/modules/auth/service.py" in failures[0]


def test_passes_when_critical_module_full_branch(tmp_path: Path) -> None:
    classes = parse_classes(_write_xml(tmp_path, {"app/modules/auth/service.py": 1.0}))
    assert check(classes, MODULES, 1.0) == []


def test_absent_module_does_not_block(tmp_path: Path) -> None:
    # Nur ein Nicht-Kritisches-Modul im Report → kritische Module ruhen.
    classes = parse_classes(_write_xml(tmp_path, {"app/main.py": 0.0}))
    assert check(classes, MODULES, 1.0) == []


def test_main_exit_codes(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.coverage_critical]\nmodules = ["app/modules/auth"]\nmin_branch_rate = 1.0\n',
        encoding="utf-8",
    )
    bad = _write_xml(tmp_path / "bad", {"app/modules/auth/x.py": 0.0})
    good = _write_xml(tmp_path / "good", {"app/modules/auth/x.py": 1.0})
    empty = _write_xml(tmp_path / "empty", {"app/main.py": 1.0})

    assert main([str(bad), str(pyproject)]) == 1
    assert main([str(good), str(pyproject)]) == 0
    assert main([str(empty), str(pyproject)]) == 0  # Module fehlen → Gate ruht.


def test_main_missing_xml_fails(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope.xml")]) == 1
