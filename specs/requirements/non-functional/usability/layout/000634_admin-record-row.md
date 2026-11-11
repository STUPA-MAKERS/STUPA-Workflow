---
id: "000634"
title: A record row in Verwaltung has one anatomy
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/src/app/pages/admin/admin-record-row.styles.spec.ts:AdminRecordRows"
implementation:
  - frontend/vendor/ui-kit/src/styles/rowgroup.scss
  - frontend/src/app/pages/admin/admin-record-row.styles.spec.ts
scope:
  - frontend/src/app/pages/admin
---

# A record row in Verwaltung has one anatomy

A row that shows one record in a list of Verwaltung must have the anatomy of the shared list
row: the content starts 24 px from the left edge, the title has the size and the weight of
the title of `app-list-item` in the text colour, and the row is at least 64 px high. An
avatar or an icon before the title keeps the 24 px start. A row of a data table and a row
of Gruppen-Zuordnung are not record rows in this sense and do not change.

Reason: A list that a page builds by itself reads as the same kind of list as a shared list
only when the start of the content, the title and the height agree. The eye follows one
left edge down the page.

Test: A source test expects the classes `rowgroup rowgroup--records` and `rowgroup__title` in
the templates of Agent-Zugänge, Vertretungen, the substitute pool, Gremium-Mitglieder,
Dokument-Varianten and the blocked senders. It expects no `padding`, no `min-height` and no
title font rule for these rows in the stylesheet of the page. A screenshot shows the lists.
