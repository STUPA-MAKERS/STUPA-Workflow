---
id: "001802"
title: The vote sheet has its add button in the head and an empty state
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/meeting-page/meeting-page.component.spec.ts:MeetingPageComponent"
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.html
scope:
  - frontend/src/app/features/meetings
---

# The vote sheet has its add button in the head and an empty state

The button that adds a vote to the open item ("Abstimmung vorbereiten", "Abstimmung öffnen" or
"Beschlussfrage hinzufügen") must be an icon button in the head of the side sheet
"Abstimmungen", in one connected button group with the close button. The same holds for
"Verknüpfen" and "To-Do anlegen" in the sheets "Verknüpft" and "To-Dos". It shows only to a person who may add a
vote.

When the item has no vote, the sheet must show the empty state "Keine Abstimmungen".

Reason: The sheet "Verknüpft" has its actions in the head too (spec 001800). A wide button
alone in an empty sheet looked like content.
