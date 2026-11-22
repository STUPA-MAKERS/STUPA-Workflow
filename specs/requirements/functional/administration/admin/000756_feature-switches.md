---
id: "000756"
title: An admin switches each feature on and off
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-22
tests:
  - "backend/tests/unit/modules/site_config/test_features.py:test_a_configuration_without_feature_entries_reads_each_feature_on"
  - "backend/tests/integration/modules/features/test_features_api.py:test_an_unknown_feature_key_is_refused"
implementation:
  - backend/app/modules/site_config/features.py
  - backend/app/modules/site_config/branding.py
  - backend/app/feature_routes.py
scope:
  - backend/app/modules
  - frontend/src/app
---

# An admin switches each feature on and off

The platform must have one switch for each of these features, in the order of the navigation:
`Aktivität` (key `activity`), `Boards` (`todos`), `Kalender` (`calendar`), `Sitzungen`
(`meetings`), `Abstimmungen` (`voting`), `Budget` (`budget`), `Rechnungen` (`invoices`),
`Tickets` (`tickets`), `Graph` (`graph`) and `Öffentliche Seiten` (`public`). Each switch must be
on in a new installation and in a configuration that does not name the feature. `Anträge`,
`Aufgaben`, `Gremien` and `Verwaltung` must not have a switch. The tab `Info` of a Gremium must
not have a switch, because an empty `Info` already does not show to a reader (001015).

A feature must include all of its parts:

- `Aktivität`: the page `Aktivität`, its dot in the navigation and its API.
- `Boards`: the boards, the cards and the card mails.
- `Kalender`: the Termine, the external calendars, the calendar subscription and the public
  calendar.
- `Sitzungen`: the meetings, the agenda, the attendance, the protocols, the delegations and the
  participation by QR code.
- `Abstimmungen`: the votes and the polls, also in a meeting.
- `Budget`: the Kostenstellen, the fiscal years and the Buchungen.
- `Rechnungen`: the invoices and their import.
- `Tickets`: the report in the help menu and the ticket work pages.
- `Graph`: the page `Graph` and its API. The permission `graph.view` still decides who sees the
  page while the feature is on.
- `Öffentliche Seiten`: the public pages `Protokolle`, `Beschlüsse` and `Kalender` with the group
  `Öffentlich` of the navigation, their cards on the public start page, the public calendar
  feed, and the link to the public version in the protocol mail. The participation by QR code
  is not a public page: it belongs to `Sitzungen`.

Reason: A student body that does not use a part of the platform must not see it. The Anträge are
the core that the flow, the forms and the Aufgaben need, and the Gremien hold the rights. A student body can use the meetings and the calendar inside
the platform without showing anything to the public.

Test: `backend/tests/unit/modules/site_config/test_features.py` reads a configuration without
feature entries and finds each feature on. `backend/tests/integration/modules/features/test_features_api.py`
sends an unknown feature key and gets 422.
