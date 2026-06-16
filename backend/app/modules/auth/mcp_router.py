"""Self-Service-Endpunkte rund um den MCP-Server (#MCP): Setup-Config + Paket-Download.

Beides ist hinter ``mcp.use`` gated (Admin bypasst). ``/config`` liefert den fertigen
``mcpServers``-Schnipsel inkl. dieser Plattform-URL; ``/package`` streamt das ``mcp/``-
Quellpaket als ``.tar.gz`` zur lokalen Installation (``pip install -e .``).
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

# Auth-Fehler-Contract (api.md §2): beide Endpunkte sind `mcp.use`-gegated → 401/403.
_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


# Aus dem Quellbaum ausgeschlossen (kein Build-/Cache-Müll im Download).
_EXCLUDE = {"__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build"}


def _is_pkg(d: Path) -> bool:
    return (d / "pyproject.toml").is_file() and (d / "antragsplattform_mcp").is_dir()


def _package_dir(settings: Settings) -> Path | None:
    """Verzeichnis des MCP-Quellpakets (`mcp/`) finden — robust über Layouts/Container.

    Reihenfolge: explizites Setting → ein bekannter Container-Mount (`/opt/mcp`) →
    Aufwärtssuche ab dieser Datei nach `mcp/pyproject.toml`. ``None``, wenn nirgends
    vorhanden (Deployment ohne Quellbaum → 404)."""
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
    """Fertiger ``mcpServers``-Eintrag für diese Plattform (zum Einfügen in den Client)."""
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
    """Das ``mcp/``-Quellpaket als ``antragsplattform-mcp.tar.gz`` streamen."""
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
        # Auto-Wiring: PUBLIC_BASE_URL ins Paket backen → kein ANTRAGSPLATTFORM_URL nötig.
        # ``json.dumps`` escaped Quotes/Newlines sicher in das Python-String-Literal
        # (kein String-Interpolations-Injection-Risiko, falls die URL je injizierbar wird).
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
