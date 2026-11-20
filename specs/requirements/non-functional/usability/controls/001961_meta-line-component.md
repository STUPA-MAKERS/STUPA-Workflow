---
id: "001961"
title: A meta line draws its dots from the kit
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/lib/meta-line
  - frontend/src/app/meta-line.templates.spec.ts
scope:
  - frontend/src/app/
---

# A meta line draws its dots from the kit

A line of parts with a middle dot between two of them ("Offen · 19.10. · AStA": the subtitle of
a list row, the facts of a calendar entry, the meta of a chat message) must be an
`app-meta-line` of the kit. The page gives only the parts, each as one element. An app template
must not write the dot itself (a `<span aria-hidden="true">·</span>`).

`app-meta-line` draws the dot before each part except the first. A part behind `@if` brings its
dot along, so no dot stands alone at the start, at the end or twice in a row when a part is
missing. The line stays in the inline flow of its place, so it changes no line height, and the
dot stands outside the box of its part, so a part with an edge (a status chip in very high
contrast) does not frame it. The dot is decorative and has no text for a screen reader.

Reason: 45 hand-written dots in 22 templates each needed an `@if` that repeated the conditions
of the parts around it, and every new part had to update them. One component keeps the dot,
its colour and its spacing the same everywhere.

Test: `frontend/src/app/meta-line.templates.spec.ts` fails on a hand-written dot in a template.
`meta-line.component.spec.ts` of the kit checks the parts and the rule. Screenshot review of the
lists of Anträge, Buchungen and the calendar, light, dark and very high contrast.
