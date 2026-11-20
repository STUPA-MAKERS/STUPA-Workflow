---
id: "001911"
title: A dialog has no footer button that only closes it
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/features/apply/observers-dialog
scope:
  - frontend/src/app/
---

# A dialog has no footer button that only closes it

A dialog or a bottom sheet whose only footer button would be "Schließen" must not show a footer.
The close button (✕) in the head closes it. A footer "Schließen" stays only where it ends a
finished step and is the only way forward, such as after a sent report or a bulk action.

Reason: Two buttons that do the same thing take room on the phone, and the footer button looks
like a main action that the dialog does not have.

Test: Screenshot review of the dialog "Beobachter:innen" on the phone.
