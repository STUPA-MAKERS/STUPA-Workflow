---
id: "002581"
title: A multiple choice in a form fills its row and names its values
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/vendor/ui-kit/src/lib/filter-select/filter-select.component.spec.ts:FilterSelectComponent"
  - "frontend/src/app/pages/admin/webhooks/webhooks.component.spec.ts:WebhooksComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/filter-select/filter-select.component.scss
  - frontend/src/app/pages/admin/webhooks/webhooks.component.ts
  - frontend/src/app/pages/admin/webhooks/webhooks.component.html
scope:
  - frontend/vendor/ui-kit/src/lib/filter-select
  - frontend/src/app/pages/admin/webhooks
---

# A multiple choice in a form fills its row and names its values

A multiple choice in a form is the select of the kit in field size (`app-filter-select`,
`size="md"`). When the form makes it wider than its text, the text must take the room and the
chevron must sit at the end edge, like the chevron of a field. Its text must be the name of the
filter while no value is chosen, else the name and the chosen values ("Gremien: AStA, StuPa").

The filters of the webhook dialog (Gremien, Antragsarten, target states) follow this rule.

Reason: In the dialog "Webhook anlegen" the filter selects filled the row, but their text
stopped at 18rem, so the chevron floated in the middle of the field. A chosen filter showed only
its name with a check mark, so the dialog did not show which Gremien a webhook filters
(Frederik 2026-11-23: "Filter sind gebrochen").

Test: The tests of the webhook page check the text of a filter with and without chosen values.
