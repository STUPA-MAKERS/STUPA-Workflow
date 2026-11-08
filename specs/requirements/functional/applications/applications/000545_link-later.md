---
id: "000545"
title: A Vorgänger linked later adds only the link
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A Vorgänger linked later adds only the link

On the detail of an existing Antrag, a user who can edit that Antrag and the Vorgänger must be able
to set, change and remove the Vorgänger. The server must check the edit right on both Anträge. This change must not change the answers of the Antrag and
must not add a submission version. Each change must write an audit entry and a timeline entry.

Reason: An Antrag that already has answers must not lose them to a copy. The link changes both
Anträge, because each detail shows it, so it needs the edit right on both. The audit and the
timeline show who connected the two Anträge.

Test: Unit tests of the link route: a caller without the edit right on one of the two Anträge
gets 403, the answers and the version count stay the same, and one
audit entry and one timeline entry exist after each change.
