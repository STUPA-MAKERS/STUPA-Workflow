"""Render one sample protocol and fail loudly if the result is no PDF.

The image build runs this module. It proves that the typst binary, the fonts,
the vendored design and the offline mitex package all load, before the image
can ship. It touches every block kind of the template once.
"""

from __future__ import annotations

import asyncio

from .compiler import default_compiler
from .document import build_document

_SAMPLE = """---
title: "Selbsttest"
gremium: "Studierendenparlament"
datum: "2026-01-01 10:00"
beginn: "10:00"
ende: "11:00"
protokoll: "Person A"
anwesend:
  - "Person A"
unterschriften:
  - "Schriftführung"
---

# Tagesordnungspunkt

Text mit **fett**, *kursiv*, `code`, ~~alt~~, 5 € -> Ziel, {{time 10:00}} und $x^2$.

> [!abstimmung] **Frage**
> ja: 3, nein: 1, enthaltung: 0

> [!beschluss] Beschluss.

> [!NOTE] Hinweis.

| a | b |
|---|--:|
| 1 | 2 |

- Punkt
  1. Unterpunkt

> Zitat

$$\\frac{1}{2}$$

```
code
```

---
"""


def main() -> None:
    for variant in ("protocol-stupa", "protocol-asta"):
        doc = build_document(_SAMPLE, variant=variant)
        pdf = asyncio.run(default_compiler().compile(doc, {}))
        assert pdf.startswith(b"%PDF"), f"selftest produced no PDF for {variant}"
        print(f"selftest ok: {variant} ({len(pdf)} bytes)")


if __name__ == "__main__":
    main()
