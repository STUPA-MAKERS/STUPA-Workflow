---
id: "000887"
title: A black bar in the PDF sits on the baseline of its line
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "typst/tests/test_integration.py:test_a_black_bar_sits_on_the_baseline"
implementation:
  - typst/template/protocol.typ
scope:
  - typst/
---

# A black bar in the PDF sits on the baseline of its line

In the protocol PDF, a black bar must sit on the baseline of the text around it. The bar must
be 1em high and reach from 0.12em below the baseline to above the cap height of the font. This applies in a paragraph,
in a list and in the grey line of a time note.

Reason: A bar that hangs below the baseline looks like a layout fault.

Test: A typst test renders a line with a bar and compares the edges of the bar with the
baseline and the cap height of the letters next to it.
