"""Self-service endpoints around the MCP server: setup config plus package download.

Both are gated behind ``mcp.use``. ``/config`` returns a ready ``mcpServers``
snippet including this platform's URL; ``/package`` streams the ``mcp/`` source
package as ``.tar.gz`` for local installation.
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


# Excluded from the source tree (no build/cache junk in the download).
_EXCLUDE = {"__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build"}


def _is_pkg(d: Path) -> bool:
    return (d / "pyproject.toml").is_file() and (d / "antragsplattform_mcp").is_dir()


def _package_dir(settings: Settings) -> Path | None:
    """Locate the MCP source package dir (`mcp/`) across layouts/containers.

    Order: explicit setting -> known container mount (`/opt/mcp`) -> upward
    search from this file. ``None`` if absent (deployment without source -> 404)."""
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
    """Ready-made ``mcpServers`` entry for this platform (paste into the client)."""
    base = settings.public_base_url.rstrip("/")
    # The downloaded package bakes in this URL → no ANTRAGSPLATTFORM_URL needed. Override
    # the scope here only if you want to narrow it.
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
    """Stream the ``mcp/`` source package as ``antragsplattform-mcp.tar.gz``."""
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
        # Bake PUBLIC_BASE_URL into the package so no ANTRAGSPLATTFORM_URL is needed.
        # ``json.dumps`` escapes quotes/newlines safely into the Python string
        # literal (no interpolation injection if the URL ever becomes injectable).
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
