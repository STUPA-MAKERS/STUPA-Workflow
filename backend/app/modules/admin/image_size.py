"""Read the pixel size of a PNG, JPEG or WebP image from its header.

The square CD logo must be square and large enough, so the server needs the
pixel size. Pillow is not a dependency, and a full decoder is not necessary to
read two numbers. These functions read only the header fields and never decode
pixel data. Each function returns ``None`` for a truncated or malformed header,
so a broken file cannot raise an index error.
"""

from __future__ import annotations

from typing import Final

_PNG_SIGNATURE: Final[bytes] = b"\x89PNG\r\n\x1a\n"

# JPEG start-of-frame markers. Each one carries the frame height and width. The
# markers C4 (DHT), C8 (JPG) and CC (DAC) share the range but are not frames.
_JPEG_SOF_MARKERS: Final[frozenset[int]] = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
# Markers without a length field: TEM and RST0..RST7.
_JPEG_STANDALONE: Final[frozenset[int]] = frozenset({0x01, *range(0xD0, 0xD8)})
# Start of scan and end of image. A frame header must come before them.
_JPEG_SOS: Final[int] = 0xDA
_JPEG_EOI: Final[int] = 0xD9

_VP8_START_CODE: Final[bytes] = b"\x9d\x01\x2a"
_VP8L_SIGNATURE: Final[int] = 0x2F
_FOURTEEN_BITS: Final[int] = 0x3FFF


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    pos = 2
    end = len(data)
    while pos + 1 < end:
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte before the marker
            pos += 1
            continue
        if marker in _JPEG_STANDALONE:
            pos += 2
            continue
        if marker in (_JPEG_SOS, _JPEG_EOI) or pos + 4 > end:
            return None
        length = int.from_bytes(data[pos + 2 : pos + 4], "big")
        if length < 2:
            return None
        if marker in _JPEG_SOF_MARKERS:
            if pos + 9 > end:
                return None
            height = int.from_bytes(data[pos + 5 : pos + 7], "big")
            width = int.from_bytes(data[pos + 7 : pos + 9], "big")
            return width, height
        pos += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8 ":
        if len(data) < 30 or data[23:26] != _VP8_START_CODE:
            return None
        width = int.from_bytes(data[26:28], "little") & _FOURTEEN_BITS
        height = int.from_bytes(data[28:30], "little") & _FOURTEEN_BITS
        return width, height
    if chunk == b"VP8L":
        if len(data) < 25 or data[20] != _VP8L_SIGNATURE:
            return None
        bits = int.from_bytes(data[21:25], "little")
        return (bits & _FOURTEEN_BITS) + 1, ((bits >> 14) & _FOURTEEN_BITS) + 1
    if chunk == b"VP8X":
        if len(data) < 30:
            return None
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None


def raster_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return the pixel size of a PNG, JPEG or WebP image.

    Args:
        data: The complete file bytes. Only the header is read.

    Returns:
        ``(width, height)`` in pixels, or ``None`` when the bytes are not one of
        the three types or the header is truncated or malformed.
    """
    if data.startswith(_PNG_SIGNATURE):
        return _png_size(data)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_size(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_size(data)
    return None
