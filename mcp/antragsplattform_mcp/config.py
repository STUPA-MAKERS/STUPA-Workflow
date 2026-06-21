"""Runtime configuration — platform URL + requested scope, supplied at MCP setup.

``ANTRAGSPLATTFORM_URL`` (required) is the platform base URL (e.g. ``https://antrag.uni.de``).
``ANTRAGSPLATTFORM_SCOPE`` (optional) is a space-separated OAuth scope list; it defaults
to the full curated set. The granted rights are still capped server-side by the logged-in
user's RBAC permissions intersected with the scope.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

CLIENT_ID = "antragsplattform-mcp"

# When the package is downloaded from a running platform, the server injects a
# ``_baked.py`` with ``BASE_URL`` set to its PUBLIC_BASE_URL → the package auto-wires and
# needs no ANTRAGSPLATTFORM_URL env var. A repo checkout has no _baked.py (env required).
try:
    from ._baked import BASE_URL as _BAKED_URL  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    _BAKED_URL = ""

# Default: ask for the full curated set; the server caps to the user's own rights and
# never grants vote.cast (ballot-casting is human-only). Narrow via ANTRAGSPLATTFORM_SCOPE.
DEFAULT_SCOPE = (
    "read applications:write votes:write budget:write "
    "meetings:write forms:write flows:write admin:write"
)


@dataclass(frozen=True)
class Config:
    base_url: str
    scope: str

    @classmethod
    def from_env(cls) -> "Config":
        # Env var wins; otherwise the URL baked in at download time (PUBLIC_BASE_URL).
        base = (os.environ.get("ANTRAGSPLATTFORM_URL", "").strip() or _BAKED_URL).strip()
        if not base:
            raise SystemExit(
                "No platform URL — set ANTRAGSPLATTFORM_URL, or download the package "
                "from your platform (it auto-wires the URL)."
            )
        scope = os.environ.get("ANTRAGSPLATTFORM_SCOPE", "").strip() or DEFAULT_SCOPE
        return cls(base_url=base.rstrip("/"), scope=scope)

    @property
    def api(self) -> str:
        return f"{self.base_url}/api"

    def token_path(self) -> Path:
        """Per-URL token cache (~/.config/antragsplattform-mcp/token-<hash>.json)."""
        key = hashlib.sha256(self.base_url.encode("utf-8")).hexdigest()[:16]
        root = Path(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        ) / "antragsplattform-mcp"
        # mode 0700: the dir holds per-URL token caches (secrets) — keep it owner-only.
        # mkdir's mode applies only on creation and is umask-masked, so it does NOT tighten
        # a pre-existing (possibly world-listable) dir — chmod afterwards to enforce 0700.
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(root, 0o700)
        except OSError:
            # Best effort: a non-owner or exotic FS may reject chmod. The token files
            # themselves are written 0o600 via os.open+os.replace, so secrets stay safe.
            pass
        return root / f"token-{key}.json"
