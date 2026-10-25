"""Build small test images in memory with Pillow."""

from __future__ import annotations

import io

from PIL import Image

_COLOR = (200, 30, 40)


def encode(fmt: str, size: tuple[int, int] = (40, 20), mode: str = "RGB", **kw: object) -> bytes:
    """Return one image of ``size`` in the Pillow format ``fmt``."""
    color: object = _COLOR if mode in ("RGB", "RGBA") else 1
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, fmt, **kw)
    return buffer.getvalue()


def animation(fmt: str, size: tuple[int, int] = (40, 20), frames: int = 3) -> bytes:
    """Return an animated GIF or WEBP with ``frames`` frames of different colors."""
    images = [Image.new("RGB", size, (i * 60 % 256, 0, 0)) for i in range(frames)]
    buffer = io.BytesIO()
    images[0].save(buffer, fmt, save_all=True, append_images=images[1:], duration=80, loop=0)
    return buffer.getvalue()


def jpeg_with_gps(size: tuple[int, int] = (60, 30), orientation: int = 1) -> bytes:
    """Return a JPEG with an EXIF orientation and a GPS block."""
    img = Image.new("RGB", size, _COLOR)
    exif = img.getexif()
    exif[0x0112] = orientation
    exif[0x010F] = "SecretCam"
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (48.0, 29.0, 0.0)
    buffer = io.BytesIO()
    img.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


def opened(data: bytes) -> Image.Image:
    """Open encoded bytes again."""
    return Image.open(io.BytesIO(data))


SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b"<script>alert(1)</script></svg>"
)
