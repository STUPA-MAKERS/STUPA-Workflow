---
id: "000535"
title: A Beschaffung shows its phase from its links
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/applications
  - backend/app/modules/budget
---

# A Beschaffung shows its phase from its links

A Beschaffung must show one phase, and the phase must come only from its links. The phases
are, in this order: `Geplant` (no linked Antrag), `Beantragt` (a linked Antrag without a
decision), `Abgelehnt` (all linked Anträge rejected), `Bewilligt` (an approved Antrag),
`Rechnung offen` (a linked invoice with status `open`) and `Bezahlt` (all linked invoices
`paid`, or a linked expense Buchung without an invoice). The latest phase that applies must be
shown. The offers must come from the positions of the linked Antrag.

Reason: A phase that a person sets by hand gets out of date. The links already hold the facts. The Antrag form already asks for offers per position.

Test: A backend unit test computes each phase from a set of links.
