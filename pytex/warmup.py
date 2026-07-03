"""Build-time cache warm-up: fetch the tectonic bundle + CD-variant packages.

Runs during ``docker build`` (with network) against ``XDG_CACHE_HOME=/cache-seed``;
the entrypoint copies the seed into the empty ``/cache`` volume on start. Without
it, tectonic lazily downloads bundle and LaTeX packages per document at runtime,
which fails behind the egress block. Rendering one realistic document per protocol
variant pulls the packages the protocol path needs into the cache.
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

# The first build may take long (bundle download); use a generous limit.
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
