---
id: "000665"
title: The empty detail pane says "Kein … geöffnet"
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/pages/tickets/tickets-none.component.spec.ts:TicketsNoneComponent"
  - "frontend/src/app/features/gremien/gremien-none/gremien-none.component.spec.ts:GremienNoneComponent"
implementation:
  - frontend/src/app/pages/tickets
  - frontend/src/app/pages/account
  - frontend/src/app/pages/admin/admin-home.component.ts
  - frontend/vendor/ui-kit/shell/src/list-none
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The empty detail pane says "Kein … geöffnet"

The detail pane without an item must show an icon and one line of the form "Kein … geöffnet"
or "Keine … geöffnet". It must not show a second line. The tickets page must say "Kein Ticket
geöffnet". Konto and Verwaltung must not show the line "Wähle links einen Bereich …".

Reason: Tickets says "ausgewählt" where all other pages say "geöffnet". The second line in
Konto and Verwaltung is a helper text (000206).

Test: A unit test of each page with a detail pane expects one line that ends with "geöffnet"
and no description.
