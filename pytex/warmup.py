"""Warm up the build cache: fetch the tectonic bundle and the CD-variant packages.

This script runs during `docker build` with network access. It writes to
`XDG_CACHE_HOME=/cache-seed`. The entrypoint copies the seed into the empty `/cache`
volume at start. Without the seed, tectonic downloads the bundle and the LaTeX packages
per document at runtime. That download fails behind the egress block.

It must render one document per variant the platform ACTUALLY ASKS FOR. It covered the
two protocol variants only, so every application PDF — which asks for `report` or
`report-makers` — hit a cold cache, tried to fetch packages at run time, and died as a
`CompileError` behind the egress block. The application render answered 400 and the job
failed with `render_error`.

That went unnoticed because applications used to be rendered with the variant of their
Gremium's corporate design, which for StuPa, AStA and ECHO was `protocol` — a warmed
variant. They compiled, as the wrong kind of document. Pinning the correct shape turned a
wrong PDF into no PDF and exposed the real gap here.
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

# An application PDF. No `typ`/`gremium`, so nothing here pulls the document towards the
# protocol path — the variant is passed explicitly anyway, and the frontmatter should not
# quietly disagree with it.
_REPORT_DOC = """---
title: Cache-Warm-up Antrag
---

# Cache-Warm-up Antrag

## Antragsdaten

Text mit **Fett**, *kursiv* und Umlauten: äöüß. LaTeX-Sonderzeichen: & % $ # _ ~ {}

- **Feld:** Wert
- **Betrag:** 1.234,56 €

## Verlauf

| Zeitpunkt | Status |
| --- | --- |
| 01.01.2026 | Eingereicht |
"""

# The first build downloads the bundle and can take a long time. Use a large limit.
_LIMITS = BuildLimits(wall_timeout_s=600.0, cpu_timeout_s=600.0)

#: Every variant the platform asks pytex for, with the source that exercises it. Keep this
#: in step with `variant_for` and `protocol_variant_for` in the backend: a variant missing
#: here compiles nowhere but a machine with internet, which is never production.
_CASES: tuple[tuple[str, str], ...] = (
    ("protocol-asta", _DOC.format(cd="asta")),
    ("protocol-stupa", _DOC.format(cd="stupa")),
    ("report", _REPORT_DOC),
    ("report-makers", _REPORT_DOC),
)


def main() -> None:
    for variant, source in _CASES:
        result = render_blob(
            BuildRequest(
                source=source.encode("utf-8"),
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
