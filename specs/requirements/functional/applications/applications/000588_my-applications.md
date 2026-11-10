---
id: "000588"
title: Meine Anträge lists the Anträge of the address
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/src/app/features/apply/my-applications.component.ts
  - frontend/src/app/features/apply/status-timeline.component.ts
  - frontend/src/app/layout/public-header/public-header.component.html
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
  - frontend/src/app/layout/public-header
---

# Meine Anträge lists the Anträge of the address

After the e-mail login, the page `/my-applications` must list every Antrag of the address in the
same list and detail layout as the Anträge page of a logged-in person:

- The list must have the search pill and month groups, newest first. A row must show the title,
  "Status · Typ" and the amount, with the approved amount when there is one.
- A row must open the detail `/my-applications/<id>` beside the list, on a phone as its own
  page. The detail must look like the internal detail: the title bar with Kommentare, Bearbeiten
  and the menu, the line "Status · Typ", the answers and the attachments beside the history, on
  a phone in the tabs Antrag, Verlauf and Anhänge.
- On a wide screen, list and detail must fill the space between the public header and the
  footer links with a small gap and no surface, line or shadow of their own.
- The page must not show the button "Antrag stellen".
- The public header must show "Abmelden" in place of "Anmelden" while the e-mail session is
  open. The page must not show a line "Angemeldet als".

An invalid, used or expired link must open `/login` with a hint.

Reason: The applicant needs one place that shows all Anträge of the address, and it must look
like the rest of the platform.

Test: `frontend/src/app/features/apply/my-applications.component.spec.ts`: the page lists the
Anträge of the session in month groups, links each row, shows no "Antrag stellen", and sends an
invalid link to `/login`; `public-header.component.spec.ts`: an e-mail session shows "Abmelden".
