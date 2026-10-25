"""Decode, clean and encode one uploaded image again (Pillow).

The upload never stores the bytes of the client. The function here decodes the image,
applies the EXIF orientation, drops every metadata block (EXIF with GPS, XMP, text
chunks, comments; an ICC profile stays, so the colors stay right), scales the longest
side down to ``MAX_SIDE`` (``MAX_ANIMATION_SIDE`` for an animation) and encodes the
pixels again in the input format. A
polyglot file or a payload in a metadata block therefore does not survive the
upload. The ClamAV scan of the client bytes runs before this decode, in
``MediaService.upload``.

The guards against a decompression bomb: libmagic must sniff one of the four types,
Pillow must read the same format, the pixel count of one frame must stay under
``MAX_PIXELS``, and an animation must stay under ``MAX_FRAMES`` frames and
``MAX_TOTAL_PIXELS`` pixels in all. Every decode error gives ``ImageRejected``.

An animation decodes one frame at a time, and each frame is scaled down before the
next one decodes. Only the scaled frames stay in memory until the encode, because
the GIF and WEBP encoders of Pillow take all frames at once.

The module imports Pillow lazily, so a process that never takes an upload does not
load it.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from app.modules.files.mime import sniff_mime
from app.modules.media.models import IMAGE_MIMES

if TYPE_CHECKING:
    from PIL.Image import Image

#: The longest side of a stored image, in pixels.
MAX_SIDE: Final[int] = 2400
#: The most pixels of one decoded frame (40 MP).
MAX_PIXELS: Final[int] = 40_000_000
#: The longest side of a stored animation, in pixels. The encoder keeps every frame in
#: memory, so an animation is stored smaller than a still image.
MAX_ANIMATION_SIDE: Final[int] = 800
#: The most frames of an animated GIF or WEBP.
MAX_FRAMES: Final[int] = 100
#: The most pixels of all frames of an animation together, before the scale-down.
MAX_TOTAL_PIXELS: Final[int] = 50_000_000
#: The largest ICC profile that the image keeps. A larger one is dropped.
MAX_ICC_BYTES: Final[int] = 256 * 1024
#: The quality of a lossy JPEG or WEBP encode.
QUALITY: Final[int] = 85

# Sniffed type -> the Pillow format name that must match it.
_FORMATS: Final[dict[str, str]] = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}


class ImageRejected(ValueError):
    """The bytes are no image of an accepted type, or they cannot be decoded."""


@dataclass(frozen=True, slots=True)
class CleanImage:
    """The encoded result of one upload."""

    data: bytes
    mime: str
    width: int
    height: int


def _target_size(width: int, height: int, max_side: int = MAX_SIDE) -> tuple[int, int]:
    longest = max(width, height)
    if longest <= max_side:
        return width, height
    scale = max_side / longest
    return max(1, round(width * scale)), max(1, round(height * scale))


def _icc(img: Image) -> bytes | None:
    icc = img.info.get("icc_profile")
    if isinstance(icc, bytes) and 0 < len(icc) <= MAX_ICC_BYTES:
        return icc
    return None


def _still(img: Image, mime: str) -> Image:
    """Return the oriented, scaled pixels of a single-frame image, without metadata."""
    from PIL import Image as PILImage
    from PIL import ImageOps

    out = ImageOps.exif_transpose(img)
    if mime == "image/jpeg":
        if out.mode not in ("RGB", "L"):
            out = out.convert("RGB")
    elif out.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
        out = out.convert("RGBA" if "A" in out.getbands() else "RGB")
    size = _target_size(out.width, out.height)
    if size != out.size:
        if out.mode in ("1", "P"):
            # A palette image scales with NEAREST only; RGBA keeps the quality.
            out = out.convert("RGBA")
        out = out.resize(size, PILImage.Resampling.LANCZOS)
    # Keep the transparency of a palette or RGB image, drop every other block.
    out.info = {k: v for k, v in out.info.items() if k == "transparency"}
    return out


def _frames(img: Image) -> tuple[list[Image], list[int]]:
    """Return the scaled RGBA frames of an animation and the duration of each.

    Each frame is converted and scaled before the next one decodes, so only one frame
    is in memory at full size.

    Raises:
        ImageRejected: A frame is not the size of the canvas. Every frame then has
            the pixels that ``_check_dimensions`` counted.
    """
    from PIL import Image as PILImage
    from PIL import ImageSequence

    frames: list[Image] = []
    durations: list[int] = []
    canvas = (img.width, img.height)
    size = _target_size(img.width, img.height, MAX_ANIMATION_SIDE)
    for frame in ImageSequence.Iterator(img):
        # A later GIF frame can reach past the canvas. Pillow then grows the image at
        # the seek, before the frame decodes, so the check of the first frame does not
        # see it. Check every frame before it decodes.
        if frame.size != canvas:
            raise ImageRejected("A frame of the animation is larger than its canvas.")
        durations.append(int(frame.info.get("duration") or 100))
        rgba = frame.convert("RGBA")
        if size != rgba.size:
            rgba = rgba.resize(size, PILImage.Resampling.LANCZOS)
        rgba.info = {}
        frames.append(rgba)
    return frames, durations


def _check_dimensions(img: Image) -> int:
    """Check the pixel guards and return the number of frames.

    Raises:
        ImageRejected: A frame or the whole animation has too many pixels, or the
            animation has too many frames.
    """
    pixels = img.width * img.height
    if pixels <= 0 or pixels > MAX_PIXELS:
        raise ImageRejected("The image has too many pixels.")
    n_frames = int(getattr(img, "n_frames", 1) or 1)
    if n_frames > MAX_FRAMES or pixels * n_frames > MAX_TOTAL_PIXELS:
        raise ImageRejected("The animation has too many frames.")
    return n_frames


def _encode(img: Image, mime: str) -> CleanImage:
    """Encode the decoded image again. ``img`` is open and its format is checked."""
    n_frames = _check_dimensions(img)
    icc = _icc(img)
    loop = int(img.info.get("loop") or 0)
    buffer = io.BytesIO()
    if n_frames > 1 and mime in ("image/gif", "image/webp"):
        frames, durations = _frames(img)
        first, rest = frames[0], frames[1:]
        options: dict[str, object] = {
            "save_all": True,
            "append_images": rest,
            "duration": durations,
            "loop": loop,
        }
        if mime == "image/gif":
            first.save(buffer, "GIF", disposal=2, **options)
        else:
            first.save(buffer, "WEBP", quality=QUALITY, **options)
        width, height = first.size
    else:
        still = _still(img, mime)
        width, height = still.size
        if mime == "image/jpeg":
            still.save(buffer, "JPEG", quality=QUALITY, icc_profile=icc)
        elif mime == "image/png":
            still.save(buffer, "PNG", icc_profile=icc)
        elif mime == "image/gif":
            still.save(buffer, "GIF")
        else:
            still.save(buffer, "WEBP", quality=QUALITY, icc_profile=icc)
    return CleanImage(data=buffer.getvalue(), mime=mime, width=width, height=height)


def clean_image(data: bytes) -> CleanImage:
    """Decode the upload and encode it again without metadata.

    Returns:
        The encoded image, in the format of the input.

    Raises:
        ImageRejected: The bytes are no PNG, JPEG, GIF or WEBP (an SVG included),
            Pillow cannot read them as the sniffed format, a pixel guard fails, or
            the decode fails.
    """
    mime = sniff_mime(data)
    if mime not in IMAGE_MIMES:
        raise ImageRejected(f"Image type not allowed: {mime}")
    from PIL import Image as PILImage
    from PIL import UnidentifiedImageError

    try:
        with warnings.catch_warnings():
            # A bomb warning of Pillow is an error here, on top of our own guards.
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
            # `formats` makes Pillow read the sniffed format only, so the two agree.
            with PILImage.open(io.BytesIO(data), formats=[_FORMATS[mime]]) as img:
                return _encode(img, mime)
    except ImageRejected:
        raise
    except (
        PILImage.DecompressionBombError,
        PILImage.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
        EOFError,
        SyntaxError,
    ) as exc:
        raise ImageRejected(f"The image cannot be decoded ({type(exc).__name__}).") from exc
