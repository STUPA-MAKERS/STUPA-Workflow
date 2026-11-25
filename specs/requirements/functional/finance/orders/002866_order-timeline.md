---
id: "002866"
title: The timeline of the Antrag shows the Bestellungen
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/applications/service/reads.py
  - frontend/src/app/shared/decision/timeline-lines.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The timeline of the Antrag shows the Bestellungen

The timeline of an Antrag must show the create, each status change and the delete of each of its
Bestellungen, with the Bezeichnung, the person and the time. An applicant session must see these
entries without a price.

Reason: The timeline is the place where a person reads what happened to an Antrag. A delivery is
such an event.

Test: A backend integration test sets "Geliefert" and finds the entry in the timeline of the
Antrag.
