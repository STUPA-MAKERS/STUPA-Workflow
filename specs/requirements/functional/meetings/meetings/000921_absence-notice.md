---
id: "000921"
title: The lead gets a mail before a member reaches the absence limit
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/meetings
  - backend/app/modules/notifications
---

# The lead gets a mail before a member reaches the absence limit

When the count of a member (000920) reaches `absenceLimit` minus 1 or `absenceLimit`, the
platform must send the mail `absence_limit`. The mail must go to the persons with
`session.manage` in the Gremium.

Reason: The Vorsitz must warn the member after the second absence and must put the loss of the
Mandat on the agenda after the third.

Test: An integration test that closes a meeting with an absent member.
