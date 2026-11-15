---
id: "000357"
title: The quorum of a protocol uses the counts of the close
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - backend/tests/integration/modules/livevote/test_roster_past_meeting.py:test_protocol_quorum_reads_the_member_count_of_the_close
  - backend/tests/unit/modules/protocol/test_header_excused.py:test_the_quorum_of_a_closed_meeting_uses_the_fixed_member_count
implementation:
  - backend/app/modules/meetings/present.py
  - backend/app/modules/protocol/service.py
scope:
  - backend/app/modules/protocol
  - backend/app/modules/livevote
---

# The quorum of a protocol uses the counts of the close

The quorum of a protocol must compare the present count of the meeting (000946) with the
number of the members with a voting right. A closed meeting must give the two values that its
close fixed. It must not use the members of today. A meeting that is not closed, and a meeting
that closed before the platform fixed the values, must count the members of the moment.

Reason: A new render of an old meeting then gives the same quorum.

Test: A backend test reads the quorum of a closed meeting with a fixed member count and of a
meeting without one.
