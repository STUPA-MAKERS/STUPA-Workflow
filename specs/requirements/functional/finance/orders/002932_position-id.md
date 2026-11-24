---
id: "002932"
title: Each position of a Kostenaufstellung has a fixed id
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/applications/position_ids.py
scope:
  - backend/app/modules/forms
  - backend/app/modules/applications
  - backend/migrations
  - frontend/src/app/pages/applications
---

# Each position of a Kostenaufstellung has a fixed id

Each position of a Kostenaufstellung must have an `id`. The server must keep an id that arrives
with a position, because the form gives a new position its id and the files of the position name
it (001730). The server must give an id to a position that arrives
without one and must keep the id of a position through later versions of the Antrag. A migration must give an id to each position of each stored version, and the same
position in two versions of an Antrag must get the same id there. The id must not change the
diff of two versions.

Reason: A Bestellung names a position (002860). A reference by the place in
the list points to a different position after an edit of the Kostenaufstellung.

Test: A backend unit test saves a position without an id and reads one, edits the Antrag and
reads the same id. A test of the migration reads the same id for the unchanged position of two
versions.
