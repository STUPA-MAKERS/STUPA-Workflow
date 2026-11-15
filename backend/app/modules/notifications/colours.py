"""Colours of the mail frame: the light and the dark set, and the accent of the branding.

A mail has no stylesheet of the app, so the frame carries its own colours. The accent
comes from the branding (§ F/collaboration/notifications/001000). An admin sets it
freely, so this module derives the link colour and the text on the button from it: each
keeps a contrast of 4.5:1 to its background (WCAG 1.4.3).

The contrast is the one of WCAG 2: the ratio of the relative luminances.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The built-in accent of the design system (`--c-accent` of the ui-kit tokens).
DEFAULT_ACCENT = "#72a384"

#: The AA contrast for normal text.
AA = 4.5

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")
_WHITE = "#ffffff"
_BLACK = "#000000"
#: The steps of a mix towards black or white; the last step is the target itself.
_STEPS = tuple(step / 20 for step in range(21))


@dataclass(frozen=True, slots=True)
class FrameColours:
    """One colour set of the mail frame (§ F/collaboration/notifications/001004)."""

    page: str
    card: str
    border: str
    text: str
    muted: str


LIGHT = FrameColours(
    page="#f2f4f8", card="#ffffff", border="#e0e4ea", text="#1f2933", muted="#5a6473"
)
DARK = FrameColours(
    page="#101214", card="#1b1e22", border="#30363d", text="#e6e9ed", muted="#a3acb8"
)


def normalize_accent(value: str | None) -> str:
    """Return ``value`` as a lower-case ``#rrggbb``, or the built-in accent."""
    low = (value or "").strip().lower()
    return low if _HEX_RE.match(low) else DEFAULT_ACCENT


def _channels(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """Return the relative luminance of WCAG 2 of a ``#rrggbb`` colour."""
    r, g, b = (_linear(c) for c in _channels(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(one: str, other: str) -> float:
    """Return the contrast ratio of WCAG 2 of two ``#rrggbb`` colours."""
    high, low = sorted((luminance(one), luminance(other)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _mix(colour: str, target: str, share: float) -> str:
    """Return ``colour`` moved by ``share`` (0 to 1) towards ``target``."""
    mixed = (
        round(c + (t - c) * share)
        for c, t in zip(_channels(colour), _channels(target), strict=True)
    )
    return "#" + "".join(f"{c:02x}" for c in mixed)


def readable(colour: str, background: str) -> str:
    """Return ``colour`` with a contrast of at least 4.5:1 to ``background``.

    The colour moves towards black on a light background and towards white on a dark
    one, in steps, until it reaches the contrast. The last step is black or white, and
    one of the two always reaches 4.5:1, so the result always has the contrast.
    """
    target = _BLACK if luminance(background) > 0.18 else _WHITE
    return next(
        mixed
        for mixed in (_mix(colour, target, step) for step in _STEPS)
        if contrast(mixed, background) >= AA or mixed == target
    )


def on_fill(fill: str) -> str:
    """Return white or black for the text on ``fill``, whichever has more contrast.

    The better one of the two has at least 4.58:1 on every colour.
    """
    return _WHITE if contrast(_WHITE, fill) >= contrast(_BLACK, fill) else _BLACK
