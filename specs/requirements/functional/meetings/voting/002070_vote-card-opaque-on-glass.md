---
id: "002070"
title: A vote card on a glass sheet is opaque in the light theme
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/features/meetings/vote-card
scope:
  - frontend/src/app/features/meetings/vote-card
---

# A vote card on a glass sheet is opaque in the light theme

In the light theme, the vote card of a meeting must have the opaque colour of the first glass
level (`--color-glass-1`, white) as its background, also on the glass of the votes sheet. The
card must not be a grey overlay of the glass. The dark theme and the display settings keep the
background that they give the card.

Reason: The content of a glass sheet turns the surface tokens into grey overlays of the glass.
On the light glass the card then is a muddy grey, and the pale tonal buttons of the ballot
(Ja, Nein, Enthaltung) and the danger button have almost no contrast to it. On white, the
buttons stand clear. In the dark theme the overlay lightens the glass and the buttons keep
their contrast.

Test: A check of the screenshots of the votes sheet in the light theme, the dark theme, very
high contrast, more contrast and less transparency.
