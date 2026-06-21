"""Tests for the token-cache directory permission hardening (AUD-024).

``Config.token_path`` must enforce mode 0o700 on the cache root even when the
directory already exists with broader permissions — ``mkdir(mode=...)`` alone
only applies on creation and is umask-masked, so a pre-existing world-listable
dir would otherwise leak the per-URL token filenames.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from antragsplattform_mcp.config import Config


def _make_config() -> Config:
    return Config(base_url="https://example.test", scope="read")


def test_token_path_creates_dir_0700(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = _make_config().token_path()
    root = path.parent
    assert root.is_dir()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_token_path_tightens_preexisting_loose_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Pre-create the cache root with world-listable perms (the AUD-024 scenario).
    root = tmp_path / "antragsplattform-mcp"
    root.mkdir(parents=True)
    os.chmod(root, 0o755)
    assert stat.S_IMODE(root.stat().st_mode) == 0o755

    _make_config().token_path()

    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_token_path_per_url_hash(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    a = Config(base_url="https://a.test", scope="read").token_path()
    b = Config(base_url="https://b.test", scope="read").token_path()
    assert a != b
    assert a.name.startswith("token-") and a.suffix == ".json"
