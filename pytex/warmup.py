"""Warm up the build cache: fetch the tectonic bundle and the CD-variant packages.

This script runs during `docker build` with network access. It writes to
`XDG_CACHE_HOME=/cache-seed`. The entrypoint copies the seed into the empty `/cache`
volume at start. Without the seed, tectonic downloads the bundle and the LaTeX packages
per document at runtime. That download fails behind the egress block. The script renders
one realistic document per protocol variant. This pulls the packages of the protocol path
into the cache.
"""

from __future__ import annotations

from pytex_api import BuildLimits, BuildRequest, InputKind, OutputKind, TrustLevel, render_blob

_DOC = """---
title: Cache-Warm-up
typ: protokoll
gremium: Warmup
cd: {cd}
datum: 2026-01-01 10:00
protokoll: Warmup
anwesend:
  - Person A
abwesend:
  - Person B
---

# TOP 1: Warm-up

Text mit **Fett**, *kursiv* und Umlauten: äöüß.

> [!abstimmung] Beschlussfrage
> Ergebnis: passed
> ja: 3, nein: 1, enthaltung: 1

| Spalte | Wert |
| --- | ---: |
| A | 1,00 € |
"""

# The first build downloads the bundle and can take a long time. Use a large limit.
_LIMITS = BuildLimits(wall_timeout_s=600.0, cpu_timeout_s=600.0)


def main() -> None:
    for cd, variant in (("asta", "protocol-asta"), ("stupa", "protocol-stupa")):
        result = render_blob(
            BuildRequest(
                source=_DOC.format(cd=cd).encode("utf-8"),
                input_kind=InputKind.MARKDOWN,
                output_kind=OutputKind.PDF,
                trust=TrustLevel.TRUSTED,
                variant=variant,
                limits=_LIMITS,
            )
        )
        assert result.output[:4] == b"%PDF", f"warmup produced no PDF for {variant}"
        print(f"warmup ok: {variant} ({len(result.output)} bytes)")


if __name__ == "__main__":
    main()
