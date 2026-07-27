"""Separate coverage gate for the critical modules (testing.md §1).

`auth`, `voting`, `flow`, `budget`, `webhooks` and `audit` must reach 100 % branch
coverage. This gate is stricter than the overall gate. The overall gate uses
`--cov-fail-under` at 85 %.

The script reads `coverage.xml` and the module list from `[tool.coverage_critical]` in
`pyproject.toml`. Run `coverage xml` first to write the report. A module whose path has
no class in the report counts as absent, and the script skips it. The gate therefore
stays green until a follow-up task adds the module. After that the gate applies again on
its own.

CLI: `python -m scripts.coverage_critical [coverage.xml] [pyproject.toml]`
Exit 0 = pass or nothing to check. Exit 1 = a module is below the minimum.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from xml.etree import ElementTree


class ClassCoverage:
    """Branch coverage of one source file, as read from coverage.xml."""

    def __init__(self, filename: str, branch_rate: float) -> None:
        self.filename = filename
        self.branch_rate = branch_rate


def load_config(pyproject: Path) -> tuple[list[str], float]:
    """Read the module prefixes and the minimum branch rate from pyproject."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    cfg = data.get("tool", {}).get("coverage_critical", {})
    modules = list(cfg.get("modules", []))
    min_rate = float(cfg.get("min_branch_rate", 1.0))
    return modules, min_rate


def parse_classes(coverage_xml: Path) -> list[ClassCoverage]:
    """Read every <class> entry of coverage.xml with its file name and branch rate."""
    root = ElementTree.parse(coverage_xml).getroot()  # noqa: S314 — our own artifact
    result: list[ClassCoverage] = []
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        rate = float(cls.get("branch-rate", "1") or "1")
        result.append(ClassCoverage(_normalize(filename), rate))
    return result


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def check(classes: list[ClassCoverage], modules: list[str], min_rate: float) -> list[str]:
    """List the coverage violations.

    Returns:
        One message for each file with a branch rate below `min_rate`. An empty list
        means the gate passes.
    """
    failures: list[str] = []
    for module in modules:
        prefix = _normalize(module)
        matched = [c for c in classes if c.filename.startswith(prefix)]
        if not matched:
            continue  # The module does not exist yet. The gate stays inactive.
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
