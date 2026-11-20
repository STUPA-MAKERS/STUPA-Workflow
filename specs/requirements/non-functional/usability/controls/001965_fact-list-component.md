---
id: "001965"
title: A list of facts comes from one kit component
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/lib/facts
  - frontend/src/app/facts.templates.spec.ts
scope:
  - frontend/src/app/
---

# A list of facts comes from one kit component

A list of facts (a label and a value, `<dl>` with `<dt>` and `<dd>`: the fields of a booking,
the time and place of a Termin, the settings of a Gremium) must be a `<dl appFacts>` (`FactsComponent`) of the kit.
An app template must not style its own `<dl>`.

`app-facts` has two layouts:

- `grid` (default): the label small and muted above the value, the facts in columns that fill
  the width (as the cards of Buchung, Rechnung and Umbuchung today). `card` puts the grid on a
  surface-2 card.
- `rows`: the label in a fixed column left of the value, one fact per line (as the Termin
  detail today).

A fact that needs the whole width is `wide`. A value wraps anywhere, so an id or an address is
never cut.

Not covered: the tally of a vote (`vc__counts`, `mtg__tally`), the figures of the Haushalt and
of a booking (`bd__figs`, `fd__figs`), the amounts of an invoice with their sum (`id__amounts`)
and the field groups of a type change (`tcd__fields`), which are numbers or lists with their own
visual weight, not facts.

Reason: 19 templates draw a fact list with five different styles (`.kv`, `apv__facts`,
`fd__card fd__grid`, `cd__fields`, `rd__ctxList` and others). The label size, the label colour
and the gaps differ from page to page for the same kind of content.

Test: a guard spec fails on a `<dl>` in an app template outside `app-facts` and the excluded
classes. Screenshot review of Buchung, Termin, Gremium settings and to-do card, light, dark and
very high contrast.
