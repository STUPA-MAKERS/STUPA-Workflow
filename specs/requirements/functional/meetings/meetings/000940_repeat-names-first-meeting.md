---
id: "000940"
title: A repeat meeting names its first meeting
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/livevote/service/lifecycle.py
  - frontend/src/app/features/meetings
scope:
  - backend/app/modules/livevote
  - backend/app/modules/meetings
  - frontend/src/app/features/meetings
---

# A repeat meeting names its first meeting

A meeting of the kind `repeat` (000903) must name an earlier meeting of the same Gremium as
its first meeting. A request that makes a repeat meeting without this meeting must be refused.
The page of the repeat meeting must link the first meeting.

Reason: The repeat quorum (000902) applies only to the Wiederholungssitzung of a Sitzung that
had no quorum. Without the first meeting, each meeting can take the lower quorum.

Test: A backend unit test makes a repeat meeting without a first meeting and gets a 422.
