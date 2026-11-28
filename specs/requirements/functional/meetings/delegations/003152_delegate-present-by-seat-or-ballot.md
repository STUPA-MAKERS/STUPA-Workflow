---
id: "003152"
title: A pool seat or a ballot marks a delegate present
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "backend/tests/integration/modules/delegations/test_delegates_attendance.py:test_a_ballot_of_the_delegate_marks_the_delegate_present"
  - "backend/tests/integration/modules/delegations/test_delegates_attendance.py:test_a_pool_seat_without_a_record_reads_present"
implementation:
  - backend/app/modules/meetings/present.py
  - backend/app/modules/meetings/attendance_service.py
  - backend/app/modules/voting/service/cast.py
scope:
  - backend/app/modules/meetings
  - backend/app/modules/voting
  - backend/app/modules/delegations
---

# A pool seat or a ballot marks a delegate present

A pool substitute on a seat (000113) without an attendance record must read `present`. A
ballot that a delegate casts for a represented member must mark the delegate `present`, as an
own ballot does for a member (000103). A status that the meeting lead set must still win over
a pool seat without a ballot.

Reason: A pool seat needs the live meeting, and a ballot needs a person in the Sitzung. The
count must not miss a delegate because nobody clicked "Anwesend".

Test: An integration test casts a ballot as a delegate and reads the delegate `present`, and
reads a pool substitute on a seat without a record as `present`.
