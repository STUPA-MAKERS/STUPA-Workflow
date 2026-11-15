"""Unit tests for `scripts/check_build_pins.py`: pinned images and build downloads."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _ROOT / "scripts" / "check_build_pins.py"
_DIGEST = "@sha256:" + "a" * 64
_HASH = "b" * 40


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_build_pins", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pins = _load()


def _tree(root: Path, dockerfile: str, compose: str, workflow: str) -> Path:
    (root / "app").mkdir()
    (root / "deploy").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "app" / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (root / "deploy" / "docker-compose.yml").write_text(compose, encoding="utf-8")
    (root / ".github" / "workflows" / "ci.yml").write_text(workflow, encoding="utf-8")
    return root


def test_the_repository_holds_the_rules() -> None:
    """§NF/compatibility/deploy/000978 and 000981: the tree of the repository is clean."""
    assert pins.check(_ROOT) == []
    assert pins.main() == 0


def test_a_pinned_tree_passes(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        f"# FROM python:3\nFROM python:3.13-slim{_DIGEST} AS base\nFROM base\nFROM scratch\n"
        "RUN curl -fsSL --retry 5 https://example.org/tool.tar.xz -o /tmp/t \\\n  && true\n",
        f"services:\n  db:\n    image: postgres:16-alpine{_DIGEST}\n",
        f"steps:\n  - uses: actions/checkout@{_HASH} # v7\n  - uses: ./.github/actions/x\n"
        "  - run: curl -sf http://127.0.0.1:8000/api/health\n"
        "  - run: curl -sf http://localhost/healthz\n",
    )
    assert pins.check(root) == []


def test_a_tag_without_a_digest_fails(tmp_path: Path) -> None:
    """§NF/compatibility/deploy/000981: a `FROM`, an `image:` and a `uses:` need a pin."""
    root = _tree(
        tmp_path,
        "FROM python:3.13-slim\n",
        "services:\n  db:\n    image: postgres:16-alpine\n",
        "steps:\n  - uses: actions/checkout@v7\n    image: redis:7\n",
    )
    errors = pins.check(root)
    assert [error.rsplit(": ", 1)[1] for error in errors] == [
        "FROM python:3.13-slim names no digest (000981)",
        "image postgres:16-alpine names no digest (000981)",
        "uses actions/checkout@v7 names no commit hash (000981)",
        "image redis:7 names no digest (000981)",
    ]


def test_a_fetched_key_and_a_download_without_a_retry_fail(tmp_path: Path) -> None:
    """§NF/compatibility/deploy/000978: no key from another server, no single try."""
    root = _tree(
        tmp_path,
        f"FROM python:3.13-slim{_DIGEST}\n"
        "RUN apt-get update \\\n"
        "    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /k.asc\n"
        'RUN curl -fsSL "$url" -o /tmp/t\n',
        "services: {}\n",
        'steps:\n  - run: |\n      curl -fsSL -o /tmp/t "https://github.com/x/y.tar.xz"\n',
    )
    errors = pins.check(root)
    assert [error.rsplit(": ", 1)[1] for error in errors] == [
        "the build fetches a signing key (000978)",
        "curl without --retry (000978)",
        "curl without --retry (000978)",
        "curl without --retry (000978)",
    ]
