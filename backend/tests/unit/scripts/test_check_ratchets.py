"""Unit tests for `scripts/check_ratchets.py`: service commits and fake sessions."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "check_ratchets.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_ratchets", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ratchets = _load()


def test_commit_calls_are_counted() -> None:
    """§S/backend/python/000640: a `commit()` call counts, another call does not."""
    tree = ast.parse(
        "async def f(s):\n"
        "    await s.commit()\n"
        "    await self.session.commit()\n"
        "    await s.flush()\n"
        "    commit()\n"
        "    s.commit(1)\n"
    )
    assert ratchets.count_commits(tree) == 2


def test_router_files_do_not_count() -> None:
    _folder, wanted, _count = ratchets.RATCHETS["service-commits"]
    assert not wanted(Path("backend/app/modules/todos/router.py"))
    assert not wanted(Path("backend/app/modules/auth/oauth_router.py"))
    assert wanted(Path("backend/app/modules/todos/service.py"))


def test_session_classes_are_counted() -> None:
    """§S/shared/testing/000642: a class with `Session` in its name counts."""
    tree = ast.parse("class _FakeSession: ...\nclass ScriptedSession: ...\nclass Other: ...\n")
    assert ratchets.count_session_classes(tree) == 2


def test_count_above_and_below_the_baseline_fails() -> None:
    errors = ratchets.compare(
        "x", {"a.py": 2, "new.py": 1, "same.py": 3}, {"a.py": 3, "same.py": 3}
    )
    assert errors == [
        "x: a.py has 2, the baseline has 3 (lower the baseline with --write)",
        "x: new.py has 1, the baseline has 0 (the count went up)",
    ]


def test_measure_reads_a_folder(tmp_path: Path) -> None:
    app = tmp_path / "backend" / "app"
    app.mkdir(parents=True)
    (app / "service.py").write_text("async def f(s):\n    await s.commit()\n")
    (app / "router.py").write_text("async def f(s):\n    await s.commit()\n")
    (app / "clean.py").write_text("x = 1\n")
    assert ratchets.measure("service-commits", tmp_path) == {"backend/app/service.py": 1}


def test_import_exceptions_are_counted_per_contract(tmp_path: Path) -> None:
    """§S/backend/python/000646: each entry of `ignore_imports` counts for its contract."""
    pyproject = (
        "[[tool.importlinter.contracts]]\n"
        'id = "layers"\n'
        'ignore_imports = ["app.a -> app.b", "app.a -> app.c"]\n'
        "[[tool.importlinter.contracts]]\n"
        'id = "clean"\n'
    )
    assert ratchets.count_import_exceptions(pyproject) == {"layers": 2, "clean": 0}
    assert ratchets.count_import_exceptions("") == {}
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text(pyproject)
    assert ratchets.measure("import-exceptions", tmp_path) == {"layers": 2}


def test_repository_equals_its_baselines() -> None:
    assert [
        line
        for name in ratchets.NAMES
        for line in ratchets.compare(name, ratchets.measure(name), ratchets._read(name))
    ] == []
