#!/usr/bin/env python3
"""Find the CI jobs that a change needs (§ S/shared/testing/001240-001244).

The `detect` job of `.github/workflows/ci.yml` runs this script. The script looks for the base
of the change: the newest green CI run whose commit is an ancestor of `HEAD` (001241). It
compares the files of the base with `HEAD` and turns the changed paths into one flag per part
of the repository (001243). A part runs when a changed path matches one of its patterns.

Every part runs (001242) when:

- the run is a push to `main`, a pull request into `main` or a manual run,
- no green base exists, or the GitHub API cannot be read,
- a changed path matches `GLOBAL`: the workflows, this script, the Nix flake or the submodules.

The script writes `key=value` lines to `$GITHUB_OUTPUT` and a table to
`$GITHUB_STEP_SUMMARY`. It needs only the Python standard library and `git`.

Usage:
    python3 scripts/ci_scope.py                 in the CI job (reads the GITHUB_* variables)
    python3 scripts/ci_scope.py --paths a b     print the parts for the paths a and b
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A change to one of these paths runs every part (001242). `*` also matches `/`.
GLOBAL: tuple[str, ...] = (
    ".github/*",
    "scripts/ci_scope.py",
    "flake.nix",
    "flake.lock",
    ".gitmodules",
)

#: The parts of the repository and the paths that each part reads (001243). A part covers its
#: own folder and every file outside it that its tests or checks read.
PARTS: Mapping[str, tuple[str, ...]] = {
    # be-lint, be-typecheck, be-unit, be-integration, be-contract, be-migrations, coverage-gate.
    "backend": (
        "backend/*",
        # tests/unit/scripts tests the check scripts, check_build_pins reads every Dockerfile
        # and the compose files, test_db_grants and the settings parity read deploy/.
        "scripts/*",
        "deploy/*",
        "*Dockerfile*",
        # tests/_support/protocols.py reads the protocol specs, test_build_uml the UML views.
        "specs/protocols/*",
        "specs/uml/*",
        # The translations module reads the UI text catalog of the frontend.
        "frontend/src/app/core/i18n/catalog/*",
        # test_cd_builtin reads the HSRT design of the typst submodule.
        "typst/vendor/*",
    ),
    # fe-unit. Its functional step reads the frontend baseline of the ratchet.
    "frontend": (
        "frontend/*",
        "scripts/check_functional.py",
        "scripts/functional-baseline/*",
    ),
    # axe runs on the compose stack: the backend, the frontend and deploy/.
    "stack": (
        "backend/*",
        "frontend/*",
        "deploy/*",
        "scripts/e2e.sh",
    ),
    # The route parity test of the MCP server reads the backend routers (001200).
    "mcp": (
        "mcp/*",
        "backend/app/*",
    ),
    "typst": ("typst/*",),
    "admin_cli": ("admin-cli/*",),
    "compose": ("deploy/*",),
    # The functional ratchet, the other ratchets and the build pins read all code, no spec.
    "functional": (
        "backend/*",
        "frontend/*",
        "mcp/*",
        "typst/*",
        "admin-cli/*",
        "deploy/*",
        "scripts/*",
        "*Dockerfile*",
    ),
}

#: The branch whose pushes and pull requests run every part (001242).
FULL_BRANCH = "main"

#: The count of green runs per query that the script tries as a base.
CANDIDATES = 30


@dataclass(frozen=True)
class Scope:
    """The result: a flag per part, the base and the reason."""

    parts: Mapping[str, bool]
    base: str
    reason: str


def matches(path: str, patterns: Iterable[str]) -> bool:
    """Return whether `path` matches one of `patterns`."""
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def full(reason: str, base: str = "") -> Scope:
    """Return the scope that runs every part."""
    return Scope(dict.fromkeys(PARTS, True), base, reason)


def scope_of(paths: Iterable[str], base: str = "") -> Scope:
    """Return the parts that the changed `paths` need."""
    changed = sorted(set(paths))
    global_hits = [path for path in changed if matches(path, GLOBAL)]
    if global_hits:
        return full(f"global file changed: {global_hits[0]}", base)
    parts = {
        part: any(matches(path, patterns) for path in changed) for part, patterns in PARTS.items()
    }
    return Scope(parts, base, f"{len(changed)} changed files since {base[:12] or 'the base'}")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def is_ancestor(sha: str, head: str = "HEAD") -> bool:
    """Return whether `sha` is a known commit and an ancestor of `head`."""
    return _git("merge-base", "--is-ancestor", sha, head).returncode == 0


def changed_paths(base: str, head: str = "HEAD") -> list[str] | None:
    """Return the paths that differ between `base` and `head`, or None when git fails."""
    result = _git("diff", "--name-only", "--no-renames", base, head)
    return result.stdout.split() if result.returncode == 0 else None


def _api(path: str, env: Mapping[str, str]) -> dict[str, object]:
    url = f"{env.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{env['GITHUB_REPOSITORY']}/{path}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {env['GH_TOKEN']}",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def green_shas(env: Mapping[str, str], *, event: str, branch: str) -> list[str]:
    """Return the head commits of the newest green CI runs for `event` on `branch`."""
    workflow = env.get("CI_WORKFLOW_FILE", "ci.yml")
    data = _api(
        f"actions/workflows/{workflow}/runs?event={event}&branch={branch}"
        f"&status=success&per_page={CANDIDATES}",
        env,
    )
    runs = data.get("workflow_runs")
    return (
        [str(run["head_sha"]) for run in runs if isinstance(run, dict)]
        if isinstance(runs, list)
        else []
    )


def candidates(env: Mapping[str, str]) -> list[str]:
    """Return the commits of the green runs that can be the base (001241)."""
    event = env.get("GITHUB_EVENT_NAME", "")
    if event == "pull_request":
        target = env.get("GITHUB_BASE_REF", "")
        own = green_shas(env, event="pull_request", branch=env.get("GITHUB_HEAD_REF", ""))
        return [*own, *green_shas(env, event="push", branch=target)]
    return green_shas(env, event="push", branch=env.get("GITHUB_REF_NAME", ""))


def decide(env: Mapping[str, str]) -> Scope:
    """Return the scope of this run from the GITHUB_* variables."""
    event = env.get("GITHUB_EVENT_NAME", "")
    if event not in ("push", "pull_request"):
        return full(f"event {event or 'unknown'} runs every part")
    target = env.get("GITHUB_BASE_REF") if event == "pull_request" else env.get("GITHUB_REF_NAME")
    if target == FULL_BRANCH:
        return full(f"{event} to {FULL_BRANCH} runs every part")
    try:
        shas = candidates(env)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as error:
        return full(f"GitHub API not readable ({error})")
    diffs = [
        (sha, paths)
        for sha in dict.fromkeys(shas)
        if is_ancestor(sha)
        for paths in [changed_paths(sha)]
        if paths is not None
    ]
    if not diffs:
        return full("no green CI run is an ancestor of this commit")
    base, paths = min(diffs, key=lambda item: len(item[1]))
    return scope_of(paths, base)


def write(scope: Scope, env: Mapping[str, str]) -> None:
    """Write the flags to $GITHUB_OUTPUT and a table to $GITHUB_STEP_SUMMARY."""
    lines = [f"{part}={'true' if flag else 'false'}" for part, flag in scope.parts.items()]
    output = env.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write("\n".join([*lines, f"base={scope.base}", ""]))
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        rows = [
            f"| {part} | {'runs' if flag else 'skipped'} |" for part, flag in scope.parts.items()
        ]
        table = [
            "### CI scope",
            "",
            scope.reason,
            "",
            "| Part | Jobs |",
            "| --- | --- |",
            *rows,
            "",
        ]
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(table))
    print(scope.reason)
    print("\n".join(lines))


def main(argv: list[str]) -> int:
    """Run the script."""
    if argv[:1] == ["--paths"]:
        write(scope_of(argv[1:]), {})
        return 0
    write(decide(os.environ), os.environ)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
