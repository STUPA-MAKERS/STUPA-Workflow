#!/usr/bin/env python3
"""Check the pins and the downloads of the image builds and the CI workflows.

- § NF/compatibility/deploy/000981: each `FROM` of a Dockerfile and each `image:` of a
  compose file or a workflow names a sha256 digest, and each `uses:` of a workflow names a
  full commit hash. A tag can move to other content, a digest and a hash cannot.
- § NF/compatibility/deploy/000978: no Dockerfile fetches a signing key, and each `curl`
  of a Dockerfile or a workflow that fetches from another server has `--retry`. One failed
  request must not fail a build.

A `FROM` that names a stage of the same Dockerfile needs no digest. A `uses:` of a local
action (`./...`) needs no hash. A `curl` to `127.0.0.1` or `localhost` is a health probe
and needs no `--retry`.

It needs only the Python standard library.

Usage:
    python3 scripts/check_build_pins.py
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", re.IGNORECASE)
_IMAGE = re.compile(r"^\s*image:\s*(\S+)")
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)")
_HASH = re.compile(r"@[0-9a-f]{40}$")
_KEY_URL = re.compile(r"https?://\S+\.(?:asc|gpg|key|pub)\b")
_REMOTE = re.compile(r"https?://(?!127\.0\.0\.1|localhost)")


def _lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield the lines with their numbers, a continued shell line as one line."""
    start, parts = 0, list[str]()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        start = start or number
        parts.append(line.removesuffix("\\"))
        if not line.endswith("\\"):
            yield start, " ".join(parts)
            start, parts = 0, []
    if parts:
        yield start, " ".join(parts)


def _code(line: str) -> str:
    """Return the line without a comment that fills it."""
    return "" if line.lstrip().startswith("#") else line


def check_dockerfile(path: Path) -> list[str]:
    """Return the violations of one Dockerfile."""
    errors, stages = list[str](), set[str]()
    for number, raw in _lines(path):
        line = _code(raw)
        found = _FROM.match(line)
        if found:
            image, stage = found.group(1), found.group(2)
            if image not in stages and image != "scratch" and "@sha256:" not in image:
                errors.append(f"{path}:{number}: FROM {image} names no digest (000981)")
            stages.update({stage} if stage else set())
        if _KEY_URL.search(line):
            errors.append(f"{path}:{number}: the build fetches a signing key (000978)")
        errors.extend(_curl_errors(path, number, line))
    return errors


def _curl_errors(path: Path, number: int, line: str) -> list[str]:
    """Return the error of a `curl` that fetches from another server without a retry."""
    commands = [part for part in re.split(r"&&|;|\|\|", line) if re.search(r"\bcurl\b", part)]
    return [
        f"{path}:{number}: curl without --retry (000978)"
        for part in commands
        if "--retry" not in part and (_REMOTE.search(part) or "$" in part.split("curl", 1)[1])
        and not re.search(r"https?://(?:127\.0\.0\.1|localhost)", part)
    ]


def check_yaml(path: Path, *, workflow: bool) -> list[str]:
    """Return the violations of one compose file or one workflow."""
    errors = list[str]()
    for number, raw in _lines(path):
        line = _code(raw)
        image = _IMAGE.match(line)
        if image and "@sha256:" not in image.group(1):
            errors.append(f"{path}:{number}: image {image.group(1)} names no digest (000981)")
        uses = _USES.match(line) if workflow else None
        if uses and not uses.group(1).startswith("./") and not _HASH.search(uses.group(1)):
            errors.append(f"{path}:{number}: uses {uses.group(1)} names no commit hash (000981)")
        errors.extend(_curl_errors(path, number, line) if workflow else [])
    return errors


def _relative(paths: Iterable[Path], root: Path) -> list[Path]:
    return sorted(path.relative_to(root) for path in paths)


def check(root: Path = ROOT) -> list[str]:
    """Return the violations of every Dockerfile, compose file and workflow under ``root``."""
    skip = {"node_modules", "vendor", ".git"}
    dockerfiles = [
        path for path in root.rglob("Dockerfile*") if not skip & set(path.relative_to(root).parts)
    ]
    composes = [*root.glob("deploy/docker-compose*.yml")]
    workflows = [*root.glob(".github/workflows/*.yml")]
    return [
        *(e for p in _relative(dockerfiles, root) for e in check_dockerfile(root / p)),
        *(e for p in _relative(composes, root) for e in check_yaml(root / p, workflow=False)),
        *(e for p in _relative(workflows, root) for e in check_yaml(root / p, workflow=True)),
    ]


def main() -> int:
    """Print the violations and return the exit status."""
    errors = [error.replace(f"{ROOT}/", "") for error in check()]
    print("\n".join(errors) if errors else "build pins: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
