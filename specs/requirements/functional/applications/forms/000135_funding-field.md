---
id: "000135"
title: The requested funding is separate from the costs
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/forms/validation.py
  - frontend/src/app/pages/admin/forms/form-editor.component.ts
scope:
  - backend/app/modules/forms
  - frontend/src/app/pages/admin
---

# The requested funding is separate from the costs

A form can have one `funding` field ("Beantragte Förderung"). Its value must be a number from 0
to the cost total. When it is filled in, it must be the amount of the Antrag. Else the amount
must be the sum of the preferred offers.
