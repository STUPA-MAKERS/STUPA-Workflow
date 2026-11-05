---
id: "000135"
title: The requested funding is separate from the costs
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - frontend/src/app/pages/admin
---

# The requested funding is separate from the costs

A form can have one `funding` field ("Beantragte Förderung"). It is a number from 0 to the cost
total. When it is filled in, it is the amount of the Antrag. Else the amount is the sum of the
preferred offers.
