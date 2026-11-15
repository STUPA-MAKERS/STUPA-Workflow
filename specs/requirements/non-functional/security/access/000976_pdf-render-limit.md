---
id: "000976"
title: A PDF made on request has a rate limit
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/shared/antiabuse.py
  - backend/app/modules/documents/router.py
  - backend/app/modules/budget/plan_router.py
  - backend/app/modules/protocol/router.py
scope:
  - backend/app/shared/antiabuse.py
  - backend/app/modules/documents
  - backend/app/modules/budget
  - backend/app/modules/protocol
---

# A PDF made on request has a rate limit

Each route that renders a PDF during the request must count against `rl_pdf_render_per_hour`
(60) for each session. These routes are the PDF of an Antrag, the export of a Haushaltsplan and
the preview of a protocol draft. Over the limit the route must answer 429 with `Retry-After`.

Reason: The render service has two places. A session that calls such a route in a loop holds
both places, and the render of a protocol at its finalization waits or fails.

Test: A backend unit test calls the limit one time more than allowed and finds the refusal. A
second test finds the limit on each of the three routes.
