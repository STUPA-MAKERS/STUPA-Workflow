---
id: "000676"
title: Verwaltung says "Tickets"
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/shared/ui-sweep.spec.ts:ticketsInAdmin"
implementation:
  - frontend/src/app/core/i18n/catalog/de.json
  - frontend/src/app/pages/admin/help-tickets
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Verwaltung says "Tickets"

The texts of Verwaltung must name a ticket "Ticket" ("Tickets ohne Konto erlauben", "Neue
Tickets per E-Mail", "Erledigte Tickets anonymisieren"). The help menu keeps the word
"Meldung" for the act of reporting ("Deine Meldung hat die Nummer …").

Reason: The list, the account and the notifications say "Tickets". A person who manages the
settings knows the item under this name.

Test: A unit test of the catalog expects no text under `admin.helpTickets` that holds
"Meldung".
