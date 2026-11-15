---
id: "000983"
title: A final protocol goes back to draft until it is approved
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation: null
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# A final protocol goes back to draft until it is approved

A person with `protocol.finalize` in the Gremium must be able to set a final protocol back
to draft while the protocol has no approval mark (000924). The platform must ask the person
before it does so. A protocol with an approval mark must answer 409 `protocol_approved`: the
person removes the mark first.

A protocol that is a draft again must behave as each draft: the corrections of 000982 are
open, and the public pages must not show the protocol or its decisions. The next
finalization must render the PDF again and must send it to the mailing list again. The
change must write the audit entry `protocol_reopen`.

Reason: A person finds an error after the finalization, before the Gremium approves the
protocol. Without a way back the error stays in the PDF. The approval of the Gremium is the
point after which the text must not change. The members got the first PDF by mail, so they
must get the corrected one.

Test: An integration test that sets a final protocol back to draft, finds it gone from the
public list, finalizes it again and finds a second mail job. One that gets 409
`protocol_approved` for a protocol with an approval mark, and one that gets 403 without
`protocol.finalize`. A frontend unit test that finds the action on a final protocol without a
mark only, and the dialog before the request.
