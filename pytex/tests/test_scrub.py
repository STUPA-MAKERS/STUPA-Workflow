"""Guard the error-detail path scrubber (AUD-075).

``_scrub`` must redact absolute filesystem paths under the known container root
prefixes (so no internal path leaks to clients) while leaving legitimate
slash-containing detail — LaTeX command fragments, fractions, URL segments —
untouched, otherwise scrubbed compile-error logs lose useful context.
"""

from __future__ import annotations

import app as app_module


def test_scrubs_container_root_paths() -> None:
    assert app_module._scrub("error in /tmp/pytex-api-abc/main.tex") == (
        "error in <path>"
    )
    assert app_module._scrub("/home/render/build.log failed") == "<path> failed"
    for root in ("tmp", "app", "cache", "home", "var", "usr", "root", "opt", "etc"):
        assert app_module._scrub(f"path: /{root}/x/y") == "path: <path>"


def test_preserves_latex_and_url_fragments() -> None:
    # LaTeX command fragments / dimensions must survive intact.
    msg = r"Undefined control sequence \fbox{0.5/linewidth}"
    assert app_module._scrub(msg) == msg
    # A bare fraction-like token is not a container path.
    assert app_module._scrub("ratio 3/4 exceeded") == "ratio 3/4 exceeded"
    # URL path segments are preserved (not a known root prefix).
    url = "see https://example.com/docs/guide for help"
    assert app_module._scrub(url) == url


def test_does_not_overmatch_arbitrary_leading_slash() -> None:
    # A leading slash followed by an unknown segment is left alone.
    assert app_module._scrub("flag /enable was set") == "flag /enable was set"
