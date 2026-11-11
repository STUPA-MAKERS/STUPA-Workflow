"""The read of an upload body with a size cap."""

from __future__ import annotations

from fastapi import UploadFile

from app.shared.errors import PayloadTooLargeError

_CHUNK = 64 * 1024


async def _read_chunks(file: UploadFile, budget: int, max_bytes: int) -> tuple[bytes, ...]:
    """Read the rest of the upload while at most ``budget`` more bytes fit the cap.

    Raises:
        PayloadTooLargeError: The body is larger than ``max_bytes`` (HTTP 413).
    """
    chunk = await file.read(_CHUNK)
    if not chunk:
        return ()
    if len(chunk) > budget:
        raise PayloadTooLargeError(f"Attachment exceeds {max_bytes} bytes.")
    return (chunk, *await _read_chunks(file, budget - len(chunk), max_bytes))


async def read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read the upload in chunks with a size cap.

    The function stops as soon as the body passes the cap. It never buffers a body that
    is larger than ``max_bytes``.

    Raises:
        PayloadTooLargeError: The body is larger than ``max_bytes`` (HTTP 413).
    """
    return b"".join(await _read_chunks(file, max_bytes, max_bytes))
