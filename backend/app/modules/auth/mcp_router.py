"""Self-service endpoints for the MCP server: setup config and package download.

Both endpoints need the `mcp.use` permission. `/config` returns a ready `mcpServers`
snippet that holds the URL of this platform. `/package` streams the `mcp/` source package
as a `.tar.gz` archive for a local installation.
"""

from __future__ import annotations

import io
import itertools
import json
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.deps import Principal, SettingsDep, require_principal
from app.modules.auth import oauth
from app.settings import Settings
from app.shared.errors import NotFoundError, ProblemDetail

router = APIRouter(prefix="/mcp", tags=["mcp"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


#: Kept out of the archive so the download holds no build or cache directory.
_EXCLUDE = {"__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build"}


def _is_pkg(d: Path) -> bool:
    return (d / "pyproject.toml").is_file() and (d / "antragsplattform_mcp").is_dir()


def _upward_candidates() -> Iterator[Path]:
    """Yield the `mcp/` directory beside each parent of this file, the nearest first.

    The generator resolves the path only on the first step, so the search touches the
    file system only after the container mount missed.
    """
    yield from (parent / "mcp" for parent in Path(__file__).resolve().parents)


def _package_dir(settings: Settings) -> Path | None:
    """Find the MCP source package directory (`mcp/`) across layouts and containers.

    The search order is the explicit setting, then the known container mount `/opt/mcp`,
    then an upward search from this file.

    Returns:
        The package directory, or `None` when the deployment ships no source. The route
        then answers 404.
    """
    explicit = Path(settings.mcp_package_dir) if settings.mcp_package_dir else None
    searched = itertools.chain((Path("/opt/mcp"),), _upward_candidates())
    return (
        next((d for d in searched if _is_pkg(d)), None)
        if explicit is None
        else (explicit if _is_pkg(explicit) else None)
    )


@router.get("/config", responses=_errors(401, 403))
def mcp_config(
    settings: SettingsDep,
    _principal: Annotated[Principal, Depends(require_principal("mcp.use"))],
) -> dict[str, Any]:
    """Return a ready-made `mcpServers` entry to paste into the MCP client.

    The downloaded package bakes in the platform URL, so the entry needs no
    ``ANTRAGSPLATTFORM_URL``. A scope override in it only narrows the scope.
    """
    base = settings.public_base_url.rstrip("/")
    return {
        "mcpServers": {
            "antragsplattform": {
                "command": "antragsplattform-mcp",
            }
        },
        "baseUrl": base,
        "clientId": settings.oauth_mcp_client_id,
        "scopesSupported": sorted(oauth.SCOPES.keys()),
        "install": "pip install -e .  # from the downloaded package directory",
        "note": (
            "The downloaded package is pre-wired to this platform URL. Set "
            "ANTRAGSPLATTFORM_SCOPE to narrow the requested scope."
        ),
    }


@router.get("/package", responses=_errors(401, 403, 404))
def mcp_package(
    settings: SettingsDep,
    _principal: Annotated[Principal, Depends(require_principal("mcp.use"))],
) -> StreamingResponse:
    """Stream the `mcp/` source package as `antragsplattform-mcp.tar.gz`.

    The package gets ``PUBLIC_BASE_URL`` baked in, so it needs no
    ``ANTRAGSPLATTFORM_URL``. ``json.dumps`` escapes quotes and newlines into the
    Python string literal, which blocks an injection if the URL ever becomes attacker
    controlled.
    """
    pkg = _package_dir(settings)
    if pkg is None:
        raise NotFoundError(
            "MCP package source is not available on this deployment "
            "(set MCP_PACKAGE_DIR or mount the mcp/ source)."
        )

    base = settings.public_base_url.rstrip("/")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
            parts = set(Path(info.name).parts)
            return None if parts & _EXCLUDE else info

        tar.add(pkg, arcname="antragsplattform-mcp", filter=_filter)
        baked = (
            '"""Auto-generated at download — pins this package to its source platform."""\n'
            f"BASE_URL = {json.dumps(base)}\n"
        ).encode()
        baked_info = tarfile.TarInfo(
            "antragsplattform-mcp/antragsplattform_mcp/_baked.py"
        )
        baked_info.size = len(baked)
        tar.addfile(baked_info, io.BytesIO(baked))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={
            "Content-Disposition": 'attachment; filename="antragsplattform-mcp.tar.gz"'
        },
    )
