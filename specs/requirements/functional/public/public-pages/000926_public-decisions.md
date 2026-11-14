---
id: "000926"
title: The decisions of a public Gremium are public
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/gremien_overview
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
---

# The decisions of a public Gremium are public

A public page must list the decisions of each Gremium that has `protocols_public`. The page
must need no session. A decision must be public only when its vote is closed, its vote is no
poll, its TOP is not internal and the protocol that records it is public
(§F/public/public-pages/000171). A public decision must show its question, its date, the title
of its meeting, its result and the sums of the votes. A public election must show its question
and its date only. A public decision must never show the name of a person.

Reason: The Geschäftsordnung asks for a Beschlusssammlung that each student can read. A
decision stays internal until its protocol is public, as the content of its meeting does.

Test: A backend unit test reads the public decisions without a session, finds the decision of
a public protocol with these fields, and does not find the decision of an internal TOP or of a
protocol that is not public.
