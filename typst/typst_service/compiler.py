"""Run `typst compile` for one document in its own sandbox root.

Each render gets a fresh temporary directory. That directory is the Typst
project root, so the compile can read nothing outside it:

    <job>/main.typ       the entry point, copied from `template/main.typ`
    <job>/doc.json       the document tree
    <job>/assets/<name>  the uploaded logos
    <job>/tpl            symlink to `template/`
    <job>/hsrt           symlink to `vendor/hsrtreport-typst/src`

Typst checks a path against the root before it follows a symlink, so the two
links expose the template and the vendored design and nothing else. The
compile runs in a subprocess with a wall-clock timeout that kills the whole
process group. Typst has no shell escape and no network access to documents,
and the service passes `--ignore-system-fonts` and an offline package path,
so the output depends on the image alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "ASSET_NAME_RE",
    "CompileError",
    "CompileTimeout",
    "TypstCompiler",
    "default_compiler",
]

_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# A plain file name with an image extension. No path separator, no leading
# dot, no `..`: the name lands in `<job>/assets/` and nowhere else.
ASSET_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*\.(?:png|jpe?g|gif|webp|svg|pdf)$",
    re.IGNORECASE,
)
_MAX_ERROR_CHARS: Final[int] = 2000


class CompileError(RuntimeError):
    """Typst rejected the document. The detail holds the compiler message."""


class CompileTimeout(RuntimeError):
    """The compile ran past the wall-clock limit and was killed."""


@dataclass(frozen=True, slots=True)
class TypstCompiler:
    """Where the typst binary and its inputs live, and how long a compile may take."""

    binary: str
    template_dir: Path
    hsrt_dir: Path
    font_dirs: tuple[Path, ...]
    package_dir: Path
    timeout_s: float

    def _command(self, root: Path, output: Path) -> list[str]:
        cmd = [
            self.binary,
            "compile",
            "--root",
            str(root),
            "--ignore-system-fonts",
            "--package-path",
            str(self.package_dir),
            # An empty cache: a package that is not vendored fails fast
            # instead of reaching for the network.
            "--package-cache-path",
            str(root / ".no-package-cache"),
            "--diagnostic-format",
            "short",
        ]
        for font_dir in self.font_dirs:
            cmd += ["--font-path", str(font_dir)]
        return [*cmd, str(root / "main.typ"), str(output)]

    def _prepare(self, root: Path, doc: dict[str, object], assets: dict[str, bytes]) -> None:
        shutil.copyfile(self.template_dir / "main.typ", root / "main.typ")
        (root / "tpl").symlink_to(self.template_dir, target_is_directory=True)
        (root / "hsrt").symlink_to(self.hsrt_dir, target_is_directory=True)
        (root / "doc.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        asset_dir = root / "assets"
        asset_dir.mkdir()
        for name, data in assets.items():
            if not ASSET_NAME_RE.fullmatch(name):
                raise CompileError(f"invalid asset name {name!r}")
            (asset_dir / name).write_bytes(data)

    async def compile(self, doc: dict[str, object], assets: dict[str, bytes]) -> bytes:
        """Compile the document tree to PDF bytes.

        Raises:
            CompileError: Typst rejected the document, or an asset name is invalid.
            CompileTimeout: The compile ran past `timeout_s`.
        """
        with tempfile.TemporaryDirectory(prefix="typst-job-") as tmp:
            root = Path(tmp)
            self._prepare(root, doc, assets)
            output = root / "out.pdf"
            proc = await asyncio.create_subprocess_exec(
                *self._command(root, output),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=root,
                start_new_session=True,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root)},
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
            except TimeoutError:
                _kill_group(proc.pid)
                await proc.wait()
                raise CompileTimeout(f"typst compile exceeded {self.timeout_s:g} s") from None
            if proc.returncode != 0 or not output.is_file():
                message = stderr.decode("utf-8", errors="replace").strip()
                raise CompileError(_scrub(message, root)[:_MAX_ERROR_CHARS] or "typst failed")
            return output.read_bytes()


def _kill_group(pid: int) -> None:
    # The process can end between the timeout and the kill.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


def _scrub(message: str, root: Path) -> str:
    """Remove the job directory from a compiler message."""
    return message.replace(str(root) + os.sep, "").replace(str(root), "")


def default_compiler() -> TypstCompiler:
    """Build the compiler from the environment, with the repository layout as default."""
    env = os.environ.get
    fonts = env("TYPST_FONT_DIRS")
    font_dirs = (
        tuple(Path(p) for p in fonts.split(os.pathsep) if p)
        if fonts
        else (_ROOT / "fonts", _ROOT / "vendor" / "hsrtreport-typst" / "src" / "assets" / "fonts")
    )
    return TypstCompiler(
        binary=env("TYPST_BIN", "typst"),
        template_dir=Path(env("TYPST_TEMPLATE_DIR", str(_ROOT / "template"))),
        hsrt_dir=Path(env("TYPST_HSRT_DIR", str(_ROOT / "vendor" / "hsrtreport-typst" / "src"))),
        font_dirs=font_dirs,
        package_dir=Path(env("TYPST_PACKAGE_DIR", str(_ROOT / "packages"))),
        timeout_s=float(env("TYPST_COMPILE_TIMEOUT_S", "60")),
    )
