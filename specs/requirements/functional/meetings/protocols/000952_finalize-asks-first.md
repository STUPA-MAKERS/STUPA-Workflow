---
id: "000952"
title: The finalize of a protocol asks first
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "frontend/src/app/features/meetings/finalize-protocol-dialog/finalize-protocol-dialog.component.spec.ts:askBeforeFinalize"
implementation:
  - frontend/src/app/features/meetings/meetings.component.ts
  - frontend/src/app/features/meetings/finalize-protocol-dialog/finalize-protocol-dialog.component.ts
scope:
  - frontend/src/app/features/meetings
---

# The finalize of a protocol asks first

The button "Finalisieren" must open the dialog "Protokoll finalisieren?" for each
protocol. The finalize must start only after the person confirms in this dialog. "Abbrechen"
must close the dialog and must not change the protocol. For a Gremium that publishes its
protocols, the dialog must also show the notice about the public page and the switch "Nicht
veröffentlichen". For each other Gremium, the dialog must not show them.

Reason: A final protocol changes only on the way back to the draft (000983). One tap by
mistake must not cause this. The mail to the members is a separate action (003019).

Test: A frontend unit test that opens the dialog for a Gremium that does not publish, finds
the question without the notice and without the switch, and gets the finalize only after the
confirmation.
