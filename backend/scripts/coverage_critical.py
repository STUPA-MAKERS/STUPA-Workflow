"""Eigenes Coverage-Gate für kritische Module (testing.md §1).

`auth`, `voting`, `flow`, `budget`, `webhooks`, `audit` müssen **100 % Branch**
erreichen. Gegen das Gesamt-Gate (85 %, via `--cov-fail-under`) ist das ein
*separates*, strengeres Gate.

Liest `coverage.xml` (`coverage xml`) und die Modul-Liste aus
`[tool.coverage_critical]` in `pyproject.toml`. Ein Modul, dessen Pfad (noch) keine
Klasse im Report hat, gilt als *nicht vorhanden* und wird übersprungen — so bleibt
das Gate grün, bis der jeweilige Folge-Task das Modul anlegt, und greift danach
automatisch.

CLI: `python -m scripts.coverage_critical [coverage.xml] [pyproject.toml]`
Exit 0 = ok/leer, Exit 1 = Unterschreitung.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from xml.etree import ElementTree


class ClassCoverage:
    """Branch-Coverage einer Quelldatei aus coverage.xml."""

    def __init__(self, filename: str, branch_rate: float) -> None:
        self.filename = filename
        self.branch_rate = branch_rate


def load_config(pyproject: Path) -> tuple[list[str], float]:
    """Modul-Prefixe + Mindest-Branch-Rate aus pyproject lesen."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    cfg = data.get("tool", {}).get("coverage_critical", {})
    modules = list(cfg.get("modules", []))
    min_rate = float(cfg.get("min_branch_rate", 1.0))
    return modules, min_rate


def parse_classes(coverage_xml: Path) -> list[ClassCoverage]:
    """Alle <class>-Einträge mit Dateiname + branch-rate aus coverage.xml."""
    root = ElementTree.parse(coverage_xml).getroot()  # noqa: S314 — eigenes Artefakt
    result: list[ClassCoverage] = []
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        rate = float(cls.get("branch-rate", "1") or "1")
        result.append(ClassCoverage(_normalize(filename), rate))
    return result


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def check(classes: list[ClassCoverage], modules: list[str], min_rate: float) -> list[str]:
    """Liste der Verstöße (Datei < min_rate). Leer = bestanden."""
    failures: list[str] = []
    for module in modules:
        prefix = _normalize(module)
        matched = [c for c in classes if c.filename.startswith(prefix)]
        if not matched:
            continue  # Modul existiert noch nicht — Gate ruht.
        for cls in matched:
            if cls.branch_rate < min_rate:
                pct = cls.branch_rate * 100
                failures.append(
                    f"{cls.filename}: branch {pct:.1f}% < {min_rate * 100:.0f}% "
                    f"(kritisches Modul {module})"
                )
    return failures


def main(argv: list[str]) -> int:
    xml_path = Path(argv[0]) if argv else Path("coverage.xml")
    pyproject = Path(argv[1]) if len(argv) > 1 else Path("pyproject.toml")

    if not xml_path.exists():
        print(f"coverage_critical: {xml_path} fehlt — erst `coverage xml` laufen lassen.")
        return 1

    modules, min_rate = load_config(pyproject)
    classes = parse_classes(xml_path)
    present = [m for m in modules if any(c.filename.startswith(_normalize(m)) for c in classes)]

    if not present:
        print("coverage_critical: keine kritischen Module im Report — Gate ruht (ok).")
        return 0

    failures = check(classes, modules, min_rate)
    if failures:
        print("coverage_critical: kritische Module unter 100 % Branch:")
        for line in failures:
            print(f"  ✗ {line}")
        return 1

    joined = ", ".join(present)
    print(f"coverage_critical: kritische Module 100 % Branch ✓ ({joined})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
