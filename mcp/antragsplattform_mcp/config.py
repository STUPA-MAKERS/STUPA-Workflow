"""Runtime configuration: the platform URL and the requested scope, set at MCP setup.

`ANTRAGSPLATTFORM_URL` (required) holds the platform base URL, for example
`https://antrag.uni.de`. `ANTRAGSPLATTFORM_SCOPE` (optional) holds a space-separated
OAuth scope list and defaults to the full curated set. The server still caps the granted
rights at the RBAC permissions of the logged-in user, intersected with the scope.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

CLIENT_ID = "antragsplattform-mcp"

# When you download the package from a running platform, the server injects a _baked.py
# with BASE_URL set to its PUBLIC_BASE_URL. The package then wires itself up and needs
# no ANTRAGSPLATTFORM_URL variable. A repository checkout has no _baked.py, so there you
# must set that variable.
try:
    from ._baked import BASE_URL as _BAKED_URL  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    _BAKED_URL = ""

# Ask for the full curated set by default. The server caps the grant at the rights of the
# user and never grants vote.cast, because only a human may cast a ballot. Narrow the set
# with ANTRAGSPLATTFORM_SCOPE.
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
        # The environment variable wins. Otherwise use the URL baked in at download time.
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
        """Return the token cache path for this platform URL.

        The path is `~/.config/antragsplattform-mcp/token-<hash>.json`.
        """
        key = hashlib.sha256(self.base_url.encode("utf-8")).hexdigest()[:16]
        root = Path(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        ) / "antragsplattform-mcp"
        # Mode 0700: the directory holds per-URL token caches, which are secrets. Keep it
        # owner-only. The mkdir mode applies only at creation and the umask masks it. It
        # does NOT tighten a directory that already exists and may be world-listable. The
        # chmod below enforces 0700 in that case.
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(root, 0o700)
        except OSError:
            # Best effort: a non-owner or an exotic file system can reject chmod. The
            # token files themselves go to disk with mode 0600 through os.open and
            # os.replace, so the secrets stay safe.
            pass
        return root / f"token-{key}.json"
