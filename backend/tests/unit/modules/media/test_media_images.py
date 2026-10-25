"""Unit tests of the image cleaning (Pillow): formats, metadata, scaling, guards."""

from __future__ import annotations

import io

import pytest
from PIL import Image, PngImagePlugin

from app.modules.media import images
from app.modules.media.images import ImageRejected, clean_image

from ._images import SVG, animation, encode, jpeg_with_gps, opened


@pytest.mark.parametrize(
    ("fmt", "mime"),
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("GIF", "image/gif"), ("WEBP", "image/webp")],
)
def test_each_format_keeps_its_format(fmt: str, mime: str) -> None:
    out = clean_image(encode(fmt))
    assert out.mime == mime
    assert (out.width, out.height) == (40, 20)
    assert opened(out.data).format == fmt


def test_jpeg_loses_exif_and_gps() -> None:
    source = jpeg_with_gps()
    assert b"SecretCam" in source
    out = clean_image(source)
    assert b"SecretCam" not in out.data
    img = opened(out.data)
    assert not img.getexif()
    assert "exif" not in img.info


def test_exif_orientation_is_applied() -> None:
    """Apply orientation 6, a 90 degree turn: 60x30 becomes 30x60."""
    out = clean_image(jpeg_with_gps(size=(60, 30), orientation=6))
    assert (out.width, out.height) == (30, 60)


def test_png_text_chunks_are_dropped() -> None:
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Comment", "geheim")
    source = encode("PNG", pnginfo=meta)
    assert b"geheim" in source
    out = clean_image(source)
    assert b"geheim" not in out.data


def test_icc_profile_stays_and_a_huge_one_goes(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = b"\x00" * 128 + b"fake-icc"
    out = clean_image(encode("PNG", icc_profile=profile))
    assert opened(out.data).info.get("icc_profile") == profile
    monkeypatch.setattr(images, "MAX_ICC_BYTES", 16)
    out = clean_image(encode("PNG", icc_profile=profile))
    assert "icc_profile" not in opened(out.data).info


def test_longest_side_is_scaled_down() -> None:
    out = clean_image(encode("JPEG", size=(4800, 1200)))
    assert (out.width, out.height) == (2400, 600)
    assert opened(out.data).size == (2400, 600)


def test_palette_image_scales_through_rgba() -> None:
    out = clean_image(encode("PNG", size=(3000, 10), mode="P"))
    assert (out.width, out.height) == (2400, 8)


def test_palette_image_keeps_transparency() -> None:
    img = Image.new("P", (8, 8), 0)
    buffer = io.BytesIO()
    img.save(buffer, "PNG", transparency=0)
    out = clean_image(buffer.getvalue())
    assert "transparency" in opened(out.data).info


def test_cmyk_jpeg_becomes_rgb() -> None:
    out = clean_image(encode("JPEG", mode="CMYK"))
    assert opened(out.data).mode == "RGB"


def test_sixteen_bit_png_becomes_rgb() -> None:
    out = clean_image(encode("PNG", mode="I;16"))
    assert opened(out.data).mode in ("RGB", "L")


@pytest.mark.parametrize(("fmt", "mime"), [("GIF", "image/gif"), ("WEBP", "image/webp")])
def test_animation_keeps_its_frames(fmt: str, mime: str) -> None:
    out = clean_image(animation(fmt, size=(4800, 100)))
    assert out.mime == mime
    assert (out.width, out.height) == (images.MAX_ANIMATION_SIDE, 17)
    img = opened(out.data)
    assert getattr(img, "n_frames", 1) == 3


@pytest.mark.parametrize("data", [SVG, b"plain text, no image at all", b""])
def test_not_an_image_is_rejected(data: bytes) -> None:
    with pytest.raises(ImageRejected, match="not allowed"):
        clean_image(data)


def test_pdf_is_rejected() -> None:
    with pytest.raises(ImageRejected):
        clean_image(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n")


def test_truncated_image_is_rejected() -> None:
    data = encode("PNG", size=(400, 400), mode="RGB")
    with pytest.raises(ImageRejected, match="cannot be decoded"):
        clean_image(data[: len(data) // 2])


def test_too_many_pixels_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "MAX_PIXELS", 100)
    with pytest.raises(ImageRejected, match="too many pixels"):
        clean_image(encode("PNG"))


def test_limits_hold_the_memory_of_an_animation_small() -> None:
    assert images.MAX_TOTAL_PIXELS == 50_000_000
    assert images.MAX_FRAMES == 100
    assert images.MAX_ANIMATION_SIDE == 800


def test_small_animation_keeps_its_size() -> None:
    out = clean_image(animation("GIF", size=(800, 10)))
    assert (out.width, out.height) == (800, 10)


def test_still_image_keeps_the_larger_side() -> None:
    out = clean_image(encode("PNG", size=(2000, 10)))
    assert (out.width, out.height) == (2000, 10)


def test_too_many_frames_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "MAX_FRAMES", 2)
    with pytest.raises(ImageRejected, match="too many frames"):
        clean_image(animation("GIF"))


def test_too_many_animation_pixels_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "MAX_TOTAL_PIXELS", 40 * 20 * 2)
    with pytest.raises(ImageRejected, match="too many frames"):
        clean_image(animation("GIF"))


def test_pillow_bomb_warning_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ImageRejected, match="cannot be decoded"):
        clean_image(encode("PNG", size=(15, 15)))


def test_pillow_bomb_error_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ImageRejected, match="cannot be decoded"):
        clean_image(encode("PNG", size=(40, 20)))


def _gif(width: int, height: int) -> bytes:
    img = Image.new("P", (width, height), 0)
    img.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    buffer = io.BytesIO()
    img.save(buffer, "GIF")
    return buffer.getvalue()


def test_frame_larger_than_its_canvas_is_rejected() -> None:
    """A second GIF frame that reaches past the canvas never decodes."""
    small, big = _gif(10, 10), _gif(60, 60)
    flags = big[10]
    start = 13 + (3 * 2 ** ((flags & 7) + 1) if flags & 0x80 else 0)
    assert big[start] == 0x2C
    data = small[:-1] + big[start:-1] + b";"
    with pytest.raises(ImageRejected, match="larger than its canvas"):
        clean_image(data)
