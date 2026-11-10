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

After the e-mail login, the page `/my-applications` must list every Antrag of the address,
newest first, in the same list and detail layout as the Anträge page of a logged-in person. A row
must show the title, the state and the date. A row must open the detail
`/my-applications/<id>` beside the list. The page must have a logout. An invalid, used or
expired link must open `/login` with a hint.

Reason: The applicant needs one place that shows all Anträge of the address, and it must look
like the rest of the platform.

Test: `frontend/src/app/features/apply/my-applications.component.spec.ts`: the page lists the
Anträge of the session, links each row, and sends an invalid link to `/login`.
