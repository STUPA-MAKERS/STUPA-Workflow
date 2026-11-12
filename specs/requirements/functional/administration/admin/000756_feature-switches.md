---
id: "000756"
title: An admin switches each feature on and off
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app
---

# An admin switches each feature on and off

The platform must have one switch for each of these features: `Boards` (key `todos`), `Kalender`
(`calendar`), `Sitzungen` (`meetings`), `Abstimmungen` (`voting`), `Budget` (`budget`),
`Rechnungen` (`invoices`) and `Tickets` (`tickets`). Each switch must be on in a new installation
and in a configuration that does not name the feature. `Anträge`, `Aufgaben`, `Gremien` and
`Verwaltung` must not have a switch.

A feature must include all of its parts:

- `Boards`: the boards, the cards and the card mails.
- `Kalender`: the Termine, the external calendars, the calendar subscription and the public
  calendar.
- `Sitzungen`: the meetings, the agenda, the attendance, the protocols with the public protocols
  page, the delegations and the participation by QR code.
- `Abstimmungen`: the votes and the polls, also in a meeting.
- `Budget`: the Kostenstellen, the fiscal years and the Buchungen.
- `Rechnungen`: the invoices and their import.
- `Tickets`: the report in the help menu and the ticket work pages.

Reason: A student body that does not use a part of the platform must not see it. The Anträge are
the core that the flow, the forms and the Aufgaben need, and the Gremien hold the rights.

Test: A backend unit test reads a configuration without feature entries and finds each feature
on. A second test sends an unknown feature key and gets 422.
