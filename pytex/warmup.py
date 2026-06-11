"""Build-time cache warm-up: tectonic-Bundle + Pakete der CD-Varianten laden.

Läuft im ``docker build`` (mit Netz) gegen ``XDG_CACHE_HOME=/cache-seed``. Der
Entrypoint kopiert den Seed beim Start in das (leere) ``/cache``-Volume — zur
LAUFZEIT braucht der Container damit kein Internet mehr: tectonic lädt Bundle
und LaTeX-Pakete sonst lazy pro Dokument nach, was hinter einer Egress-Sperre
mit »error sending request … operation timed out« jeden Render killt.

Gewärmt wird je Protokoll-Variante ein realistisches Dokument (Vote-Callout,
Tabelle, Logos) — das zieht die im Protokoll-Pfad benötigten Pakete in den Cache.
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

# Erst-Build darf lange dauern (Bundle-Download) — großzügiges Limit.
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
