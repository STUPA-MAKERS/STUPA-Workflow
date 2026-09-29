"""Unit tests for the compile runner, with a stand-in typst binary."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from typst_service.compiler import (
    ASSET_NAME_RE,
    CompileError,
    CompileTimeout,
    TypstCompiler,
    default_compiler,
)


def _fake_binary(tmp_path: Path, script: str) -> str:
    path = tmp_path / "fake-typst"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _compiler(tmp_path: Path, binary: str, timeout: float = 5) -> TypstCompiler:
    base = default_compiler()
    return TypstCompiler(
        binary=binary,
        template_dir=base.template_dir,
        hsrt_dir=base.hsrt_dir,
        font_dirs=base.font_dirs,
        package_dir=base.package_dir,
        timeout_s=timeout,
    )


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("0a1b-logo.png", True),
        ("Logo.SVG", True),
        ("x.pdf", True),
        ("a.jpeg", True),
        ("../x.png", False),
        ("a/b.png", False),
        (".x.png", False),
        ("x.png.exe", False),
        ("x", False),
    ],
)
def test_asset_name_rule(name: str, ok: bool) -> None:
    assert bool(ASSET_NAME_RE.fullmatch(name)) is ok


def test_compile_writes_the_job_root_and_returns_the_pdf(tmp_path: Path) -> None:
    # The fake binary checks the sandbox layout and the flags, then writes
    # the output file, which is the last argument.
    script = r"""
for a in "$@"; do last="$a"; done
root="$(dirname "$last")"
test -f "$root/main.typ" || exit 3
test -f "$root/doc.json" || exit 4
test -f "$root/tpl/protocol.typ" || exit 5
test -d "$root/hsrt/assets" || exit 6
test "$(cat "$root/assets/l.png")" = "PNGDATA" || exit 7
case " $* " in *" --ignore-system-fonts "*) ;; *) exit 8 ;; esac
printf '%%PDF-fake' > "$last"
"""
    comp = _compiler(tmp_path, _fake_binary(tmp_path, script))
    pdf = asyncio.run(comp.compile({"title": "x"}, {"l.png": b"PNGDATA"}))
    assert pdf == b"%PDF-fake"


def test_compile_error_carries_the_scrubbed_message(tmp_path: Path) -> None:
    script = 'echo "error: bad thing in $PWD/main.typ" >&2; exit 1\n'
    comp = _compiler(tmp_path, _fake_binary(tmp_path, script))
    with pytest.raises(CompileError) as info:
        asyncio.run(comp.compile({}, {}))
    assert "bad thing in main.typ" in str(info.value)
    assert "typst-job-" not in str(info.value)


def test_compile_without_output_is_an_error(tmp_path: Path) -> None:
    comp = _compiler(tmp_path, _fake_binary(tmp_path, "exit 0\n"))
    with pytest.raises(CompileError, match="typst failed"):
        asyncio.run(comp.compile({}, {}))


def test_invalid_asset_name_is_refused(tmp_path: Path) -> None:
    comp = _compiler(tmp_path, _fake_binary(tmp_path, "exit 0\n"))
    with pytest.raises(CompileError, match="invalid asset name"):
        asyncio.run(comp.compile({}, {"../evil.png": b""}))


def test_timeout_kills_the_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "child-alive"
    # The child keeps running in the background; the kill must reach it too.
    script = f'(sleep 3; touch "{marker}") &\nsleep 30\n'
    comp = _compiler(tmp_path, _fake_binary(tmp_path, script), timeout=0.5)
    with pytest.raises(CompileTimeout):
        asyncio.run(comp.compile({}, {}))
    asyncio.run(asyncio.sleep(3.5))
    assert not marker.exists()


def test_default_compiler_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPST_BIN", "/opt/typst")
    monkeypatch.setenv("TYPST_FONT_DIRS", os.pathsep.join(["/f1", "/f2"]))
    monkeypatch.setenv("TYPST_COMPILE_TIMEOUT_S", "7")
    comp = default_compiler()
    assert comp.binary == "/opt/typst"
    assert comp.font_dirs == (Path("/f1"), Path("/f2"))
    assert comp.timeout_s == 7
