---
id: "003153"
title: The protocol names a delegate with the represented members
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "backend/tests/integration/modules/delegations/test_delegates_attendance.py:test_the_protocol_names_the_delegate"
implementation:
  - backend/app/modules/protocol/service/document.py
scope:
  - backend/app/modules/protocol
---

# The protocol names a delegate with the represented members

The attendance lines of the protocol ("Anwesend", "Entschuldigt", "Abwesend") must hold each
delegate with the status of the delegate (003150, 003152). The entry must name the represented
members: "Lea Kurz (für Max Muster)". The public version must count the delegates and must not
name them.

Reason: The protocol is the record of the Sitzung. It must show who was in the room and for
whom, and its list must agree with the count.

Test: An integration test builds the protocol document of a meeting with a present delegate
and finds the entry with the represented member in the line "Anwesend".
