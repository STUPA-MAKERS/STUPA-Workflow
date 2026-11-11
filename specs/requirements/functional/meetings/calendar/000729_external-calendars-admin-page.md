---
id: "000729"
title: The admin page Kalender lists and edits the external calendars
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/pages/admin
---

# The admin page Kalender lists and edits the external calendars

The admin area must have the page `Kalender` at `/admin/calendars` in the group `Gremien` of the
admin navigation. Only a person with the permission `admin.calendars` must be able to open the page
and to change an external calendar. The calendar of a Gremium must also be set on this page only.

The page must show one row for each external calendar. A row must show the name, the state of the
newest fetch as status text (`Abgerufen` or `Abruf fehlgeschlagen`), the scope (`Alle` or the name
of the Gremium) and the URL. The body of a row must show the state, the time of the newest attempt,
the time of the newest success, the number of entries and the reason of a failure.

The button `Kalender abonnieren` and a press on a row must open a dialog with the fields `Name`,
`ICS-Adresse`, the choice `Alle | Ein Gremium`, for `Ein Gremium` the field `Gremium`, and the
field `Aktualisieren` with the values `Alle 15 Minuten`, `Stündlich`, `Alle 6 Stunden` and
`Täglich`. The
dialog must refuse a URL that does not start with `https://`.

The menu of a row must have the actions `Jetzt abrufen`, `Bearbeiten` and `Löschen`. `Löschen`
must ask for a confirmation and must remove the calendar together with its entries.

Reason: An admin must see at one place which calendars the platform reads and why a calendar
shows no new entries. One place for all scopes keeps the rule of who sets a calendar simple.

Test: A backend unit test calls each route of the external calendars without `admin.calendars`
and gets 403. A second test deletes a calendar and finds none of its entries.
