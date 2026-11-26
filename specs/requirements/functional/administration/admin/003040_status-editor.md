---
id: "003040"
title: The pages Bestellzustände and Veranstaltungszustände edit a list without a sequence
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-26
implementation:
  - frontend/src/app/pages/admin/statuses/statuses.component.html
  - frontend/vendor/ui-kit/src/lib/step-list/step-list.component.ts
scope:
  - frontend/src/app/pages/admin
  - backend/app/modules/statuses
---

# The pages Bestellzustände and Veranstaltungszustände edit a list without a sequence

Each status list must have its own page under Verwaltung (003035): `Bestellzustände` for the
list of the Bestellungen, shown only while the feature of the Bestellungen is on, and
`Veranstaltungszustände` for the list of the Events. Each page must show the field
`Startzustand` above the list, a dropdown with the statuses of the kind `open`. Each page must
edit its list with the kit component `app-step-list` without numbers: per row the name, the
delete button and the selects of the row (`Art`, color, and for a Bestellung the date of
003037), and the add button under the list. A row must have no buttons up and down, because the
statuses have no sequence. A new status goes to the end of the list. The pages must have no
styles of their own (002213). A status must show in the lists and details of its element in the
same way as the state of a Haushaltsplan version. The storage must follow the schema of the plan
steps: one row per status with the list, the position and its values.

Reason: A list without numbers and without moves says that the statuses have no sequence. The
start status is one choice of the whole list, so it is one field. One page per list says on its
name which element it configures.

Test: A frontend unit test adds a status on the page Bestellzustände, picks it as the start
status and reads the request, reads that the rows have no numbers and no move buttons, and reads
that the page Veranstaltungszustände sends only the list of the Events.
