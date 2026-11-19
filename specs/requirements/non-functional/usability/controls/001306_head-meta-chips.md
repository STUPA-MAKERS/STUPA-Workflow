---
id: "001306"
title: The meta line in the head of a detail is a list of chips
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/pages/applications/applications-detail.header.spec.ts:metaChips"
implementation:
  - frontend/vendor/ui-kit/src/styles/_meta-chips.scss
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.scss
  - frontend/src/app/pages/budget/_finance-sheet.scss
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app
---

# The meta line in the head of a detail is a list of chips

The line below the title of a detail must show its facts as a list of chips, not as text with a
middle dot between the facts. This holds for the head of a Gremium, an Antrag, a Rechnung, a
Buchung, an Umbuchung, a selection of Buchungen, a Haushalt sheet, a Ticket and an Abstimmung.

1. Each fact must be a chip: the grey pill of the app chips, in the small font. A chip of a fact
   is not a control and must have no press state.
2. A status in the line must be its status chip (001305), with no second pill around it.
3. The chips must wrap onto the next line when the line is too short. No line may start with a
   dot.
4. In very high contrast a chip of a fact must have no fill and a thin white edge, so that it
   does not look like a choice (000615) or a state (000605).
5. A list row keeps its dots. The phone bar of the meeting head keeps its dots, because the bar
   has one small line below the title.

Reason: A long line of facts with dots between them reads as one sentence. Chips show where one
fact ends and the next one starts, and they look like the status chip beside them.

Test: A frontend unit test that finds the facts of the Antrag head as separate chips, with no
dot in the line.
