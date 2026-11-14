---
id: "000928"
title: A page asks whether the reader reads a plan and gets no 403
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_readable_route_answers_200_without_the_read_right"
  - "frontend/src/app/core/api/api-client.service.spec.ts:ApiClient"
implementation:
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/core/api/api-client.service.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/features/voting
  - frontend/src/app/features/meetings
---

# A page asks whether the reader reads a plan and gets no 403

A page that shows the vote on a Haushaltsplan or its item on an agenda must ask the
platform whether the reader reads that plan before it shows the link to the plan.
`GET /api/budget-plan-versions/{id}/readable` must answer 200 with `readable` true or false
for each signed-in person, also for a version that does not exist. The page must not read
the plan itself to find that out, and must show no link when the answer is false.

Reason: A member of a Gremium that votes on a plan often has no read right on the Haushalt.
A read of the plan then answers 403. The page hides that answer, but the browser writes it
to its console as an error, and a person who looks for a fault finds an error that is none.

Test: The router test reads 200 with true for a reader, and 200 with false for a person
without the read right and for a version that does not exist. The test of the API client
reads the answer of the new route.
