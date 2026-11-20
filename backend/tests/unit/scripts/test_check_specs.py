"""Unit tests for `scripts/check_specs.py`: the § sign in a spec and taken numbers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "check_specs.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_specs", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_specs"] = module
    spec.loader.exec_module(module)
    return module


check_specs = _load()


def test_a_section_sign_before_a_rule_is_found() -> None:
    """§S/specs/format/000032: a spec refers to a rule without the § sign."""
    body = "See (§F/meetings/voting/000024) and §ui-kit:000744 and §000026."
    assert len(check_specs.spec_section_refs(body)) == 3


def test_a_law_and_inline_code_keep_the_section_sign() -> None:
    """§S/specs/format/000032: the paragraph of a law and an example in code are allowed."""
    body = "LHO § 33 and § 10 L-BGG apply. Write `§F/meetings/voting/000024` in the code."
    assert check_specs.spec_section_refs(body) == []


def test_a_number_that_the_base_branch_took_is_an_error() -> None:
    """§S/specs/format/000006: a number of the base branch does not name a second spec."""
    local = {"000950": "a/b/000950_info-tab.md", "000001": "s/f/000001_one.md"}
    base = {"000950": "m/p/000950_draft-pdf.md", "000001": "s/f/000001_one.md"}
    fork = {"000001": "s/f/000001_one.md"}
    errors = check_specs.base_collisions(local, base, fork)
    assert len(errors) == 1
    assert "000950" in errors[0]


def test_a_known_number_and_a_moved_spec_are_no_error() -> None:
    """§S/specs/format/000006: a spec that the branch knew keeps its number."""
    fork = {"000001": "s/f/000001_one.md", "000002": "s/f/000002_two.md"}
    local = {
        "000001": "s/f/000001_one.md",
        "000002": "s/g/000002_two.md",
        "000003": "s/f/000003_x.md",
    }
    base = {"000001": "s/f/000001_one.md", "000002": "s/f/000002_two.md"}
    assert check_specs.base_collisions(local, base, fork) == []
