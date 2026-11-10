---
id: "000634"
title: A record row in Verwaltung has one anatomy
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/pages/admin
---

# A record row in Verwaltung has one anatomy

A row that shows one record in a list of Verwaltung must have the anatomy of the shared list
row: the content starts 24 px from the left edge, the title has the size and the weight of
the title of `app-list-item` in the text colour, and the row is at least 64 px high. An
avatar or an icon before the title keeps the 24 px start. A row of a data table and a row
of Gruppen-Zuordnung are not record rows in this sense and do not change.

Reason: The rows that a page builds by itself start at 16 px (Vertretungen,
Dokument-Varianten) while the shared rows start at 24 px (Rollen, Webhooks, Audit-Log).
The title is 14 px semibold in the accent colour on Vertretungen and 15 px medium in the
text colour on the other pages.

Test: A screenshot shows the lists of Agent-Zugänge, Vertretungen, Gremium-Mitglieder and
Dokument-Varianten beside Rollen. A source test expects no `padding-inline` and no title
`font` rule for these rows outside the shared row style.
