---
id: "000760"
title: A feature that needs another feature goes off with it
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app
---

# A feature that needs another feature goes off with it

`Rechnungen` needs `Budget`. While `Budget` is off, `Rechnungen` must be off, and the switch of
`Rechnungen` must be locked and must show the text `Benötigt Budget`. When `Budget` goes on again,
`Rechnungen` must return to the state that the admin set before.

A feature that only shows records of another feature does not need it. `Kalender` stays on while
`Sitzungen` is off, and `Sitzungen` stays on while `Abstimmungen` is off.

Reason: An invoice books on a Kostenstelle, so the invoices cannot work without the budget. One
press must be enough to switch a feature off.

Test: A backend unit test switches `Budget` off and gets `feature_disabled` from an invoice
route. It switches `Budget` on again and reads the stored state of `Rechnungen`.
