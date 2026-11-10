---
id: "000618"
title: In very high contrast, a choice card has a yellow edge and a yellow circle
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:choiceCards"
implementation:
  - frontend/src/app/features/voting/ballot/ballot.component.scss
  - frontend/src/app/features/apply
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# In very high contrast, a choice card has a yellow edge and a yellow circle

While "Sehr hoher Kontrast" is on, a choice card must have a black fill, yellow text, a 2 px
yellow edge and an empty yellow circle in front of the text. The chosen card must have a yellow
fill, black text and a black circle with a tick. A choice card is a vote option, a vote option for
a person that the voter stands in for, and a card of the Antrag type in the wizard.

Reason: The circle shows that exactly one option applies, also before a person chose one. A vote
must leave no doubt about that.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` expects the yellow edge and the
circle on a choice card and the yellow fill on the chosen card.
