---
id: "003151"
title: A present delegate counts as present
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "backend/tests/unit/modules/meetings/test_present.py:test_a_present_delegate_counts_one_time"
  - "backend/tests/integration/modules/delegations/test_delegates_attendance.py:test_a_present_delegate_counts_in_the_one_count"
  - "frontend/src/app/shared/present-count.util.spec.ts:presentCount"
implementation:
  - backend/app/modules/meetings/present.py
  - frontend/vendor/ui-kit/views/meeting/src/present-count.util.ts
  - frontend/src/app/shared/present-count.util.ts
scope:
  - backend/app/modules/meetings
  - backend/app/modules/voting
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# A present delegate counts as present

A delegate with the attendance status `present` must count in the one count of present
members (000946), and so in the quorum (000900). The delegate must count one time, also with
several delegations, and also when the delegate is a present member. A delegate with the
status `excused` or `absent` must not count. A delegation without the voting right must make
nobody a delegate.

Reason: A Vertretung takes the place of an absent member in the room. The pool seat already
counts so (000113). One count on the page and in the protocol must also hold for the other
delegations.

Test: A unit test counts a meeting with a present delegate who holds two delegations, an
absent delegate and a present member who is a delegate, and finds each present person once.
