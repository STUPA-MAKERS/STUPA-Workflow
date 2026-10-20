#!/usr/bin/env python3
"""Render the iOS launch images (apple-touch-startup-image) into public/splash/.

iOS shows a white screen while an installed web app starts, also in the dark theme,
unless index.html links a launch image of the exact screen size of the device. Each
image is the page background of a theme with the app mark in the centre, at a quarter
of the screen width, so the start looks like the first frame of the app.

The mark comes from public/icons/icon-512x512.png (the mark on an opaque white square).
The white is taken out as alpha, so the mark sits on the dark background without a
white box. The images are palette PNGs, a few KB each.

Run from frontend/ after a change of the sizes, the colours or the icon:

    python3 scripts/make-splash.py

Then copy the <link> lines it prints into src/index.html. Needs Pillow.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "public" / "icons" / "icon-512x512.png"
OUT = ROOT / "public" / "splash"

# The page background (--color-bg of the ui-kit tokens) per theme.
THEMES = {"light": (0xF6, 0xF7, 0xF5), "dark": (0x10, 0x12, 0x11)}

# The six colours of the mark (src/assets/logos/stupa-mark.svg).
MARK_COLOURS = [
    (0x29, 0x23, 0x5C),
    (0xF1, 0x87, 0x00),
    (0x00, 0x8B, 0x92),
    (0xCE, 0x16, 0x25),
    (0x00, 0x75, 0xBF),
    (0xFF, 0xCC, 0x00),
]

# The portrait screens of the iPhones that run a current iOS: CSS width, CSS height and
# the device pixel ratio. One entry covers every model with the same screen.
SCREENS = [
    (375, 667, 2),  # iPhone SE 2nd and 3rd gen, 8, 7, 6s
    (414, 736, 3),  # iPhone 8 Plus, 7 Plus
    (375, 812, 3),  # iPhone X, XS, 11 Pro, 12 mini, 13 mini
    (414, 896, 2),  # iPhone XR, 11
    (414, 896, 3),  # iPhone XS Max, 11 Pro Max
    (390, 844, 3),  # iPhone 12, 12 Pro, 13, 13 Pro, 14, 16e
    (428, 926, 3),  # iPhone 12 Pro Max, 13 Pro Max, 14 Plus
    (393, 852, 3),  # iPhone 14 Pro, 15, 15 Pro, 16
    (430, 932, 3),  # iPhone 14 Pro Max, 15 Plus, 15 Pro Max, 16 Plus
    (402, 874, 3),  # iPhone 16 Pro, 17, 17 Pro
    (420, 912, 3),  # iPhone Air
    (440, 956, 3),  # iPhone 16 Pro Max, 17 Pro Max
]


def mark() -> Image.Image:
    """The mark of the icon, cut to its bounds, with the white background as alpha.

    Each pixel of the icon is a colour of the mark over white: c = a*P + (1 - a)*W. The
    pixel takes the colour P of the mark that explains it best, and its share a as the
    alpha, so the inside of a shape is opaque in its own colour and only the edges blend
    into the background of the theme.
    """
    icon = Image.open(ICON).convert("RGB")
    out = Image.new("RGBA", icon.size)
    pixels: list[tuple[int, int, int, int]] = []
    raw = icon.tobytes()
    for i in range(0, len(raw), 3):
        c = (raw[i], raw[i + 1], raw[i + 2])
        best = (float("inf"), MARK_COLOURS[0], 0.0)
        for colour in MARK_COLOURS:
            d = [255 - p for p in colour]
            e = [255 - v for v in c]
            share = max(
                0.0, min(1.0, sum(x * y for x, y in zip(d, e, strict=True)) / sum(x * x for x in d))
            )
            error = sum((y - share * x) ** 2 for x, y in zip(d, e, strict=True))
            if error < best[0]:
                best = (error, colour, share)
        _, colour, share = best
        pixels.append((*colour, round(share * 255)))
    out.putdata(pixels)
    bbox = out.getbbox()
    if bbox is None:
        raise SystemExit(f"{ICON} holds no mark")
    return out.crop(bbox)


def splash(
    logo: Image.Image, width: int, height: int, background: tuple[int, int, int]
) -> Image.Image:
    """One launch image: the background with the mark at a quarter of the width."""
    size = round(width / 4)
    scaled = logo.resize((size, round(logo.height * size / logo.width)), Image.Resampling.LANCZOS)
    image = Image.new("RGB", (width, height), background)
    image.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2), scaled)
    # A flat background and six colours with their edges: 64 palette entries keep the
    # edges smooth and the file small.
    return image.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    logo = mark()
    links = []
    for theme, background in THEMES.items():
        for w, h, ratio in SCREENS:
            name = f"splash-{theme}-{w * ratio}x{h * ratio}.png"
            splash(logo, w * ratio, h * ratio, background).save(OUT / name, optimize=True)
            media = (
                f"(device-width: {w}px) and (device-height: {h}px)"
                f" and (-webkit-device-pixel-ratio: {ratio}) and (orientation: portrait)"
                f" and (prefers-color-scheme: {theme})"
            )
            links.append(
                f'<link rel="apple-touch-startup-image" media="{media}" href="splash/{name}" />'
            )
    print("\n".join(links))


if __name__ == "__main__":
    main()
