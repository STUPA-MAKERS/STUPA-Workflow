---
id: "002800"
title: A sheet from the phone dock of a meeting opens over the whole screen
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.scss
scope:
  - frontend/src/app/features/meetings/meeting-page
---

# A sheet from the phone dock of a meeting opens over the whole screen

On a phone, a bottom sheet that the dock of a meeting opens (Protokollführung wählen,
Protokollführung übergeben) must open at the bottom edge of the screen, over the navigation bar,
with its head, its search and its full list. The dock must not cut the sheet off or hold it
inside its own box. The dock itself must keep its frosted glass.

Reason: The dock is a box of frosted glass, and a backdrop filter makes its box the frame of
every fixed box inside it. The sheet of the Protokollführung then opened inside the dock, so only
one cut-off person row showed (Frederik, dev instance on a phone, 2026-11-24).

Test: A person checks on phone screenshots that the sheet opens over the whole width at the
bottom edge, in both themes and with very high contrast and reduced transparency, and that the
desktop popover does not change.
