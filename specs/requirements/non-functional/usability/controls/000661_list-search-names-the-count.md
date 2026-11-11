---
id: "000661"
title: The search field of a list names the count
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/pages/applications
  - frontend/src/app/pages/tasks
  - frontend/src/app/pages/expenses
  - frontend/src/app/pages/invoices
  - frontend/src/app/pages/tickets
  - frontend/src/app/pages/todos
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
  - frontend/src/app/features/voting
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The search field of a list names the count

The search field of a list page must show the placeholder "N … durchsuchen", where N is the
number of items in the list and "…" is the name of the items. For one item the name must be
in the singular ("1 Ticket durchsuchen"). The pattern is that of Anträge. It applies to
Anträge, Aufgaben, Buchungen, Rechnungen, Sitzungen, Tickets, Gremien, Abstimmungen and the
boards.

A search field that searches a part of a page, for example the cost centres of the budget
tree or the settings of Verwaltung, must show "… durchsuchen" without a count.

Reason: The lists use four patterns ("8 Anträge durchsuchen", "Aufgaben durchsuchen",
"Beschreibung suchen …", "Suchen (Nummer, Lieferant) …"), and three lists have no singular
("1 Tickets durchsuchen").

Test: A unit test of each list page renders it with no item, one item and two items and
expects the placeholder of the pattern.
