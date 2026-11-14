---
id: "000897"
title: The vote form offers five majority rules
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "frontend/src/app/features/meetings/vote-open-dialog/vote-open-dialog.component.spec.ts:VoteOpenDialogComponent"
implementation:
  - frontend/src/app/features/meetings/vote-open-dialog/vote-open-dialog.component.ts
scope:
  - frontend/src/app/features/voting
  - frontend/src/app/features/meetings
  - backend/app/modules/voting
---

# The vote form offers five majority rules

The form of a motion must offer the rules "Einfache Mehrheit", "Absolute Mehrheit der Stimmen",
"Zweidrittelmehrheit der Stimmen", "Mehrheit der Mitglieder" and "Zweidrittelmehrheit der
Mitglieder". The form must start with "Einfache Mehrheit".

Reason: The person who opens the vote knows which majority the Satzung asks for.

Test: A component test of the vote form.
