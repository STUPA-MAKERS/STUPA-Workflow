"""Virus scanning with ClamAV/clamd: the ``VirusScanner`` protocol and ``ScanVerdict``.

The worker scans an uploaded attachment with the ``clamd`` INSTREAM command, after the
upload (quarantine). ``scan_or_raise`` scans in the request, before the upload is
stored: invoice PDFs, Markdown images, CD logos and inline branding logos use it. The module imports
``clamd`` lazily, because only a configured scanner needs it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.settings import Settings
from app.shared.errors import ServiceUnavailableError, UnsupportedMediaTypeError

# The official EICAR test signature. It is not a real virus. Quarantine tests and fakes
# use it.
EICAR_TEST_BYTES = (
    rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


class ScannerError(RuntimeError):
    """ClamAV is unreachable or the scan failed. The worker retries and fails closed."""


@dataclass(frozen=True, slots=True)
class ScanVerdict:
    """Scan result.

    When ``clean`` is false, ``signature`` carries the finding.
    """

    clean: bool
    signature: str | None = None


class VirusScanner(Protocol):
    """Scan interface that the worker uses."""

    async def scan(self, data: bytes) -> ScanVerdict: ...


@dataclass(slots=True)
class ClamdScanner:
    """clamd backend over TCP INSTREAM.

    The blocking call runs in a thread pool.
    """

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
    """Build a clamd scanner from the settings.

    Returns:
        The scanner, or ``None`` when ClamAV is off.
    """
    if not settings.clamav_enabled:
        return None
    assert settings.clamav_host is not None
    return ClamdScanner(
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout_seconds=settings.clamav_timeout_seconds,
    )


async def scan_or_raise(data: bytes, settings: Settings) -> None:
    """Scan the bytes of an upload in the request and raise on a bad verdict.

    The caller calls this before it stores the bytes, so an infected file never
    reaches the bucket. Without ClamAV the scan is skipped outside ``production``,
    which covers development and contract CI. In ``production`` a missing or failed
    scanner fails closed, so the server never stores an unscanned upload. This
    matches the quarantine of the attachments.

    Raises:
        ServiceUnavailableError: The scanner is missing in production or the scan
            failed (503).
        UnsupportedMediaTypeError: The scanner found a signature (415). The detail
            names the signature.
    """
    scanner = build_scanner(settings)
    if scanner is None:
        if settings.is_production:
            raise ServiceUnavailableError("Virus scan unavailable.")
        return
    try:
        verdict = await scanner.scan(data)
    except ScannerError as exc:
        raise ServiceUnavailableError("Virus scan unavailable.") from exc
    if not verdict.clean:
        raise UnsupportedMediaTypeError(
            f"File rejected by virus scan: {verdict.signature or 'unknown'}"
        )
