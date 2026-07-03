"""Virus scanning (ClamAV/clamd): ``VirusScanner`` protocol + ``ScanVerdict``.

The worker scans the uploaded object via ``clamd`` INSTREAM. ``clamd`` is imported
lazily (only needed on the worker path).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.settings import Settings

# Official EICAR test signature (not a real virus) for quarantine tests/fakes.
EICAR_TEST_BYTES = (
    rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


class ScannerError(RuntimeError):
    """ClamAV unreachable or scan failed; worker retries (fail-closed)."""


@dataclass(frozen=True, slots=True)
class ScanVerdict:
    """Scan result. When ``clean=False``, ``signature`` carries the finding."""

    clean: bool
    signature: str | None = None


class VirusScanner(Protocol):
    """Scan interface used by the worker."""

    async def scan(self, data: bytes) -> ScanVerdict: ...


@dataclass(slots=True)
class ClamdScanner:
    """clamd backend (TCP INSTREAM). Blocking call runs in a threadpool."""

    host: str
    port: int = 3310
    timeout_seconds: float = 60.0

    def _scan_sync(self, data: bytes) -> ScanVerdict:
        import io

        import clamd

        daemon = clamd.ClamdNetworkSocket(
            host=self.host, port=self.port, timeout=self.timeout_seconds
        )
        # clamd format: {"stream": ("OK"|"FOUND", signature_or_None)}
        result = daemon.instream(io.BytesIO(data))
        if not result or "stream" not in result:
            raise ScannerError("clamd returned no result")
        status, signature = result["stream"]
        if status == "OK":
            return ScanVerdict(clean=True)
        return ScanVerdict(clean=False, signature=signature or "unknown")

    async def scan(self, data: bytes) -> ScanVerdict:
        try:
            return await asyncio.to_thread(self._scan_sync, data)
        except Exception as exc:  # noqa: BLE001 - transient -> ScannerError (retry)
            raise ScannerError(f"scan failed: {type(exc).__name__}") from exc


def build_scanner(settings: Settings) -> VirusScanner | None:
    """Build a clamd scanner from settings; ``None`` when ClamAV is disabled."""
    if not settings.clamav_enabled:
        return None
    assert settings.clamav_host is not None
    return ClamdScanner(
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout_seconds=settings.clamav_timeout_seconds,
    )
