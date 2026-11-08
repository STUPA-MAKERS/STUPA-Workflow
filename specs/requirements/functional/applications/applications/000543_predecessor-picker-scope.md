---
id: "000543"
title: The Vorgänger picker lists only readable Anträge
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# The Vorgänger picker lists only readable Anträge

The Vorgänger picker must list only the Anträge of the same Antragstyp that the caller can open
in the Anträge list.
For a logged-in user, that is the read scope of the list: `application.read`,
`application.read_all`, the Gremium read scope, and every Antrag that the user created while
logged in. The server must check the read right of the chosen Vorgänger again when it saves
the link. A caller who is not logged in must not see the picker.

Reason: The picker must not show the title of an Antrag that the caller cannot open. A guest
has no read scope, because a magic link covers only its own Antrag.

Test: Unit tests of the link route: a Vorgänger outside the read scope fails with 403, and a
guest submission with a Vorgänger fails with 403.
