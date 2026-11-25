---
id: "001630"
title: The Kostenaufstellung shows the total cost and the requested amount
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-24
replaced_by: F/applications/forms/003010
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# The Kostenaufstellung shows the total cost and the requested amount

Below the positions of a `positions` field, the form must show one line:
`Gesamtkosten X €, davon beantragt Y €` (`Total cost X €, of which requested Y €`). X is the sum
of the preferred offers. Y is the value of the `funding` field (000135) when the form has one and
it is filled in, else X. The line must update while the applicant types.

Reason: Prod data holds 7 Anträge with a question or a correction about the amount and 5 with the grant entered as a cost position. The applicant did not see the difference between the cost and the grant.

Test: A frontend unit test renders the line with and without a `funding` value.
