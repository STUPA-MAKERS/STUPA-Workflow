"""Self-service endpoints for the MCP server: setup config and package download.

Both endpoints need the `mcp.use` permission. `/config` returns a ready `mcpServers`
snippet that holds the URL of this platform. `/package` streams the `mcp/` source package
as a `.tar.gz` archive for a local installation.
"""

from __future__ import annotations

import io
import json
import tarfile
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
    return {code: _PROBLEM for code in codes}


# Kept out of the archive so the download holds no build or cache directory.
_EXCLUDE = {"__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build"}


def _is_pkg(d: Path) -> bool:
    return (d / "pyproject.toml").is_file() and (d / "antragsplattform_mcp").is_dir()


def _package_dir(settings: Settings) -> Path | None:
    """Find the MCP source package directory (`mcp/`) across layouts and containers.

    The search order is the explicit setting, then the known container mount `/opt/mcp`,
    then an upward search from this file.

    Returns:
        The package directory, or `None` when the deployment ships no source. The route
        then answers 404.
    """
    if settings.mcp_package_dir:
        cand = Path(settings.mcp_package_dir)
        return cand if _is_pkg(cand) else None
    mount = Path("/opt/mcp")
    if _is_pkg(mount):
        return mount
    for parent in Path(__file__).resolve().parents:
        cand = parent / "mcp"
        if _is_pkg(cand):
            return cand
    return None


@router.get("/config", responses=_errors(401, 403))
def mcp_config(
    settings: SettingsDep,
    _principal: Annotated[Principal, Depends(require_principal("mcp.use"))],
) -> dict[str, Any]:
    """Return a ready-made `mcpServers` entry to paste into the MCP client."""
    base = settings.public_base_url.rstrip("/")
    # The downloaded package bakes in this URL, so ANTRAGSPLATTFORM_URL is not needed.
    # Override the scope here only to narrow it.
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
    """Stream the `mcp/` source package as `antragsplattform-mcp.tar.gz`."""
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
        # Bake PUBLIC_BASE_URL into the package so ANTRAGSPLATTFORM_URL is not needed.
        # `json.dumps` escapes quotes and newlines into the Python string literal. This
        # blocks an interpolation injection if the URL ever becomes attacker controlled.
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
