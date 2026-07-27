"""Guard the error-detail path scrubber (AUD-075).

`_scrub` must redact an absolute filesystem path under a known container root
prefix, so no internal path leaks to a client. It must leave other detail with a
slash untouched: a LaTeX command fragment, a fraction or a URL segment.
Otherwise a scrubbed compile-error log loses useful context.
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
    # A LaTeX command fragment or a dimension must survive intact.
    msg = r"Undefined control sequence \fbox{0.5/linewidth}"
    assert app_module._scrub(msg) == msg
    # A bare fraction-like token is not a container path.
    assert app_module._scrub("ratio 3/4 exceeded") == "ratio 3/4 exceeded"
    # A URL path segment carries no known root prefix, so it stays.
    url = "see https://example.com/docs/guide for help"
    assert app_module._scrub(url) == url


def test_does_not_overmatch_arbitrary_leading_slash() -> None:
    # The scrubber leaves a leading slash with an unknown segment alone.
    assert app_module._scrub("flag /enable was set") == "flag /enable was set"
