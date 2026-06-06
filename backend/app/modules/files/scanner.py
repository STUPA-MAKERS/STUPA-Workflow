"""Virenscan (ClamAV/clamd) — ``VirusScanner``-Protokoll + ``ScanVerdict``.

Der Worker scannt das hochgeladene Objekt über ``clamd`` (INSTREAM). Ergebnis ist ein
:class:`ScanVerdict` (``clean`` + optionale Signatur). Transport bleibt austauschbar:
Tests injizieren einen Stub-Scanner (clean / EICAR), produktiv läuft ``ClamdScanner``.

``clamd`` wird **lazy** importiert (nur im Worker-Pfad nötig).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.settings import Settings

# Offizielle EICAR-Testsignatur (kein echter Virus) — für Quarantäne-Tests/-Fakes.
EICAR_TEST_BYTES = (
    rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


class ScannerError(RuntimeError):
    """ClamAV nicht erreichbar / Scan fehlgeschlagen (→ Retry im Worker)."""


@dataclass(frozen=True, slots=True)
class ScanVerdict:
    """Scan-Ergebnis. ``clean=False`` → ``signature`` trägt den Fund."""

    clean: bool
    signature: str | None = None


class VirusScanner(Protocol):
    """Vom Worker genutzte Scan-Schnittstelle."""

    async def scan(self, data: bytes) -> ScanVerdict: ...


@dataclass(slots=True)
class ClamdScanner:
    """clamd-Backend (TCP INSTREAM). Blockierender Call → Threadpool."""

    host: str
    port: int = 3310
    timeout_seconds: float = 60.0

    def _scan_sync(self, data: bytes) -> ScanVerdict:
        import io

        import clamd

        daemon = clamd.ClamdNetworkSocket(
            host=self.host, port=self.port, timeout=self.timeout_seconds
        )
        # clamd-Format: {"stream": ("OK"|"FOUND", signature_or_None)}
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
        except Exception as exc:  # noqa: BLE001 — transient → ScannerError (Retry)
            raise ScannerError(f"scan failed: {type(exc).__name__}") from exc


def build_scanner(settings: Settings) -> VirusScanner | None:
    """clamd-Scanner aus den Settings bauen — ``None``, wenn ClamAV »aus« ist."""
    if not settings.clamav_enabled:
        return None
    assert settings.clamav_host is not None
    return ClamdScanner(
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout_seconds=settings.clamav_timeout_seconds,
    )
