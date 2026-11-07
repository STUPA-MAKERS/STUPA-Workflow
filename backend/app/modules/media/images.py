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

#: Sniffed type -> the Pillow format name that must match it.
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


def _still_mode(img: Image, mime: str) -> str | None:
    """Return the mode that a still image converts to before the encode, or None to keep it."""
    match mime:
        case "image/jpeg":
            return None if img.mode in ("RGB", "L") else "RGB"
        case _:
            keep = img.mode in ("1", "L", "LA", "P", "RGB", "RGBA")
            return None if keep else ("RGBA" if "A" in img.getbands() else "RGB")


def _scaled(img: Image, size: tuple[int, int]) -> Image:
    """Scale ``img`` to ``size``; a palette or bilevel image goes through RGBA first."""
    from PIL import Image as PILImage

    if size == img.size:
        return img
    base = img.convert("RGBA") if img.mode in ("1", "P") else img
    return base.resize(size, PILImage.Resampling.LANCZOS)


def _with_info(img: Image, info: dict[str | tuple[int, int], object]) -> Image:
    """Replace the info blocks of ``img`` and return it.

    Pillow keeps the metadata in the mutable ``info`` of the image, so the only way to
    drop it is to overwrite that attribute in place.
    """
    img.info = info
    return img


def _still(img: Image, mime: str) -> Image:
    """Return the oriented, scaled pixels of a single-frame image, without metadata.

    A palette image scales with NEAREST only, so it converts to RGBA to keep the quality.
    The transparency of a palette or RGB image stays. Every other info block goes.
    """
    from PIL import ImageOps

    oriented = ImageOps.exif_transpose(img)
    mode = _still_mode(oriented, mime)
    converted = oriented if mode is None else oriented.convert(mode)
    scaled = _scaled(converted, _target_size(converted.width, converted.height))
    return _with_info(scaled, {k: v for k, v in scaled.info.items() if k == "transparency"})


def _frame(img: Image, canvas: tuple[int, int], size: tuple[int, int]) -> tuple[Image, int]:
    """Return one animation frame as scaled RGBA without metadata, and its duration.

    Raises:
        ImageRejected: The frame is not the size of the canvas.
    """
    from PIL import Image as PILImage

    if img.size != canvas:
        raise ImageRejected("A frame of the animation is larger than its canvas.")
    duration = int(img.info.get("duration") or 100)
    rgba = img.convert("RGBA")
    scaled = rgba if size == rgba.size else rgba.resize(size, PILImage.Resampling.LANCZOS)
    return _with_info(scaled, {}), duration


def _frames(img: Image) -> tuple[list[Image], list[int]]:
    """Return the scaled RGBA frames of an animation and the duration of each.

    Each frame is converted and scaled before the next one decodes, so only one frame
    is in memory at full size.

    A later GIF frame can reach past the canvas. Pillow then grows the image at the seek,
    before the frame decodes, so the check of the first frame does not see it. The function
    therefore checks every frame before it decodes.

    Raises:
        ImageRejected: A frame is not the size of the canvas. Every frame then has
            the pixels that ``_check_dimensions`` counted.
    """
    from PIL import ImageSequence

    canvas = (img.width, img.height)
    size = _target_size(img.width, img.height, MAX_ANIMATION_SIDE)
    pairs = tuple(_frame(frame, canvas, size) for frame in ImageSequence.Iterator(img))
    return [frame for frame, _ in pairs], [duration for _, duration in pairs]


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


def _animation(img: Image, mime: str, loop: int) -> tuple[bytes, tuple[int, int]]:
    """Encode the frames of an animated GIF or WEBP; return the bytes and the size."""
    frames, durations = _frames(img)
    first, rest = frames[0], frames[1:]
    options: dict[str, object] = {
        "save_all": True,
        "append_images": rest,
        "duration": durations,
        "loop": loop,
    }
    buffer = io.BytesIO()
    match mime:
        case "image/gif":
            first.save(buffer, "GIF", disposal=2, **options)
        case _:
            first.save(buffer, "WEBP", quality=QUALITY, **options)
    return buffer.getvalue(), first.size


def _single(img: Image, mime: str, icc: bytes | None) -> tuple[bytes, tuple[int, int]]:
    """Encode a single-frame image in its own format; return the bytes and the size."""
    still = _still(img, mime)
    buffer = io.BytesIO()
    match mime:
        case "image/jpeg":
            still.save(buffer, "JPEG", quality=QUALITY, icc_profile=icc)
        case "image/png":
            still.save(buffer, "PNG", icc_profile=icc)
        case "image/gif":
            still.save(buffer, "GIF")
        case _:
            still.save(buffer, "WEBP", quality=QUALITY, icc_profile=icc)
    return buffer.getvalue(), still.size


def _encode(img: Image, mime: str) -> CleanImage:
    """Encode the decoded image again. ``img`` is open and its format is checked.

    The ICC profile and the loop count are read before the frames decode, because a
    seek to a later frame can change ``img.info``.
    """
    n_frames = _check_dimensions(img)
    icc = _icc(img)
    loop = int(img.info.get("loop") or 0)
    animated = n_frames > 1 and mime in ("image/gif", "image/webp")
    data, (width, height) = _animation(img, mime, loop) if animated else _single(img, mime, icc)
    return CleanImage(data=data, mime=mime, width=width, height=height)


def clean_image(data: bytes) -> CleanImage:
    """Decode the upload and encode it again without metadata.

    A bomb warning of Pillow is an error here, on top of the own guards. ``formats`` makes
    Pillow read the sniffed format only, so the two agree.

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
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
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
