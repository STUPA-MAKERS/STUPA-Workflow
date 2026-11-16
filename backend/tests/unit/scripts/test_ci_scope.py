"""Unit tests for `scripts/ci_scope.py`: the parts of the CI that a change needs."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "ci_scope.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_scope", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci = _load()


def _on(paths: list[str]) -> set[str]:
    return {part for part, flag in ci.scope_of(paths).parts.items() if flag}


def test_spec_change_runs_no_part() -> None:
    """§S/shared/testing/001240: a change of a rule spec runs only the job specs."""
    assert _on(["specs/style/shared/testing/000048_run-integration.md", "specs/README.md"]) == set()


def test_frontend_change_runs_frontend_and_stack() -> None:
    """§S/shared/testing/001240: a frontend change runs fe-unit, axe and the ratchets."""
    assert _on(["frontend/src/app/app.component.ts"]) == {"frontend", "stack", "functional"}


def test_backend_change_runs_mcp_too() -> None:
    """§S/shared/testing/001243: the MCP parity test reads the backend routers."""
    assert _on(["backend/app/modules/voting/router.py"]) == {
        "backend",
        "stack",
        "mcp",
        "functional",
    }


def test_backend_test_change_does_not_run_mcp() -> None:
    """§S/shared/testing/001243: the MCP part reads only backend/app."""
    assert "mcp" not in _on(["backend/tests/unit/test_health.py"])


@pytest.mark.parametrize(
    ("path", "part"),
    [
        ("frontend/src/app/core/i18n/catalog/de.json", "backend"),
        ("specs/protocols/integrations/webhooks/x.schema.json", "backend"),
        ("specs/uml/classes.json", "backend"),
        ("typst/vendor/hsrtreport-typst", "backend"),
        ("deploy/db/roles.sql", "backend"),
        ("frontend/Dockerfile", "backend"),
        ("scripts/functional-baseline/frontend-app.json", "frontend"),
        ("frontend/vendor/ui-kit", "frontend"),
        ("deploy/docker-compose.yml", "stack"),
        ("scripts/e2e.sh", "stack"),
        ("deploy/docker-compose.yml", "compose"),
        ("typst/src/main.py", "typst"),
        ("admin-cli/antragsplattform_admin/app.py", "admin_cli"),
    ],
)
def test_a_read_file_runs_its_part(path: str, part: str) -> None:
    """§S/shared/testing/001243: a file that a part reads runs that part."""
    assert part in _on([path])


@pytest.mark.parametrize(
    "path",
    [".github/workflows/ci.yml", "scripts/ci_scope.py", "flake.lock", ".gitmodules"],
)
def test_global_file_runs_every_part(path: str) -> None:
    """§S/shared/testing/001242: a change of the CI itself runs every part."""
    scope = ci.scope_of(["specs/README.md", path])
    assert all(scope.parts.values())
    assert path in scope.reason


@pytest.mark.parametrize(
    "env",
    [
        {"GITHUB_EVENT_NAME": "workflow_dispatch"},
        {"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": "main"},
        {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_BASE_REF": "main"},
    ],
)
def test_main_and_dispatch_run_every_part(env: dict[str, str]) -> None:
    """§S/shared/testing/001242: main and a manual run run every part."""
    assert all(ci.decide(env).parts.values())


def test_unreadable_api_runs_every_part(monkeypatch: pytest.MonkeyPatch) -> None:
    """§S/shared/testing/001241: without a known green run every part runs."""

    def fail(*_args: object, **_kwargs: object) -> list[str]:
        raise OSError("no network")

    monkeypatch.setattr(ci, "green_shas", fail)
    scope = ci.decide({"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": "development"})
    assert all(scope.parts.values())
    assert "not readable" in scope.reason


def test_no_ancestor_runs_every_part(monkeypatch: pytest.MonkeyPatch) -> None:
    """§S/shared/testing/001241: a green run off the history is no base."""
    monkeypatch.setattr(ci, "green_shas", lambda *_a, **_k: ["0" * 40])
    scope = ci.decide({"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": "development"})
    assert all(scope.parts.values())
    assert scope.base == ""


def _commit(repo: Path, name: str) -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(name, encoding="utf-8")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
    return git("rev-parse", "HEAD")


def test_base_is_the_green_run_with_the_smallest_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§S/shared/testing/001241: the newest green ancestor sets the changed paths."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    old = _commit(tmp_path, "backend/app/a.py")
    new = _commit(tmp_path, "frontend/src/a.ts")
    _commit(tmp_path, "specs/style/a.md")
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    monkeypatch.setattr(
        ci,
        "green_shas",
        lambda *_a, event, **_k: [old] if event == "push" else [new, "f" * 40],
    )
    scope = ci.decide(
        {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_BASE_REF": "development",
            "GITHUB_HEAD_REF": "feature",
        }
    )
    assert scope.base == new
    assert not any(scope.parts.values())


def test_write_sets_outputs(tmp_path: Path) -> None:
    """§S/shared/testing/001240: the flags reach the outputs of the job detect."""
    output = tmp_path / "out"
    summary = tmp_path / "summary"
    scope = ci.scope_of(["typst/src/main.py"], "abc")
    ci.write(scope, {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)})
    lines = output.read_text(encoding="utf-8").splitlines()
    assert "typst=true" in lines
    assert "backend=false" in lines
    assert "base=abc" in lines
    assert "| typst | runs |" in summary.read_text(encoding="utf-8")


def test_paths_flag_prints_parts(capsys: pytest.CaptureFixture[str]) -> None:
    """§S/shared/testing/001240: `--paths` shows the parts of a list of paths."""
    assert ci.main(["--paths", "mcp/README.md"]) == 0
    assert "mcp=true" in capsys.readouterr().out
