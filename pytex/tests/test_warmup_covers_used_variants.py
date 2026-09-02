"""The warm-up must cover every variant the platform asks for.

This exists because it did not, and the gap cost a production feature. The warm-up
rendered the two protocol variants only, so an application PDF — which asks for `report`
or `report-makers` — met a cold cache, tried to fetch its LaTeX packages at run time, and
died behind the container's egress block. pytex answered 400 and the job failed with
`render_error`.

Nothing caught it, because every test that renders runs on a machine with internet, where
a cold cache is a slow success rather than a failure. A cache miss is only fatal in
production. So the check here is not "does it render" but "is the variant listed at all" —
a property that holds without a network and without tectonic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_WARMUP = Path(__file__).resolve().parents[1] / "warmup.py"

#: What the backend asks pytex for. Keep in step with `variant_for` in
#: `backend/app/modules/pdf/markdown.py` and `protocol_variant_for` in
#: `backend/app/modules/protocol/markdown.py`.
#:
#: Duplicated here rather than imported: the backend is a separate package that this
#: service must not depend on, and a copy that a test compares beats a coupling that a
#: deployment cannot honour.
REQUESTED_BY_THE_PLATFORM = frozenset(
    {
        # Applications: `variant_for` maps "makers" to report-makers and everything else
        # to the default "report".
        "report",
        "report-makers",
        # Protocols: `protocol_variant_for` maps the stupa and asta designs.
        "protocol-stupa",
        "protocol-asta",
    }
)


def _warmed() -> set[str]:
    """The variant names the warm-up actually builds."""
    src = _WARMUP.read_text(encoding="utf-8")
    return set(re.findall(r'\(\s*"([a-z][a-z-]*)"\s*,\s*_', src))


@pytest.mark.parametrize("variant", sorted(REQUESTED_BY_THE_PLATFORM))
def test_the_warmup_covers(variant: str) -> None:
    assert variant in _warmed(), (
        f"{variant!r} is requested by the platform but never warmed. "
        "Its packages would be fetched at run time, which fails behind the egress block."
    )


def test_every_warmed_variant_is_a_real_one() -> None:
    """A typo would warm nothing and only surface as a failed image build."""
    from pytex_builder.variants import VARIANT_NAMES

    unknown = _warmed() - set(VARIANT_NAMES)
    assert not unknown, f"warm-up names variants pytex does not have: {sorted(unknown)}"
