---
id: "001602"
title: The timeline shows a decision made outside the platform
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/flow
  - frontend/src/app/pages/applications
---

# The timeline shows a decision made outside the platform

The timeline of the Antrag must show a decision made outside the platform (001600) as
`Beschluss außerhalb der Plattform` (`Decision outside the platform`). The entry must show the
result, the date of the meeting and the Gremium. When they were given, it must also show the
counts and the link to the meeting or the protocol. The applicant must see the entry without
the name of the person who recorded it.

Reason: The reader of an Antrag must see where and when the decision was made, also when the platform did not hold the vote.

Test: A frontend unit test renders the timeline entry with and without the optional values.
