---
id: "000588"
title: Meine Anträge lists the Anträge of the address
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
---

# Meine Anträge lists the Anträge of the address

After the e-mail login, the page `/meine-antraege` must list every Antrag of the address,
newest first. A row must show the title, the number, the state and the date of the Antrag, and
must open the Antrag at `/antrag/<id>`. The page must have a logout.

Reason: The applicant needs one place that shows all Anträge of the address.

Test: `frontend/src/app/features/apply/my-applications.component.spec.ts`: the page lists the
Anträge of the session and links each row.
