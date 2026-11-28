---
id: "000983"
title: A final protocol goes back to draft until it is approved
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "backend/tests/integration/modules/protocol/test_protocol_draft_and_approval.py:test_a_final_protocol_goes_back_to_draft_until_it_is_approved"
  - "backend/tests/integration/modules/protocol/test_public_protocols.py:test_a_reopened_protocol_leaves_the_public_page_until_it_is_final_again"
  - "backend/tests/unit/modules/protocol/test_protocol_service.py:test_a_send_before_the_last_finalization_does_not_count"
  - "frontend/src/app/features/meetings/protocol-bar/protocol-bar.component.spec.ts:reopenProtocol"
implementation:
  - backend/app/modules/protocol/approval.py
  - backend/app/modules/protocol/service/drafts.py
  - backend/app/modules/protocol/router.py
  - frontend/vendor/ui-kit/views/protocol/src/protocol-bar-view.component.ts
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
finalization must render the PDF again. The protocol must then count as not sent until the
person sends it again (003019). A draft
that was final before must not be deletable (000117). The change must write the audit entry
`protocol_reopen`.

Reason: A person finds an error after the finalization, before the Gremium approves the
protocol. Without a way back the error stays in the PDF. The approval of the Gremium is the
point after which the text must not change. The members got the first PDF by mail, so they
must be able to get the corrected one.

Test: An integration test that sets a final protocol back to draft and gets 409
`protocol_approved` for a protocol with an approval mark. One that finds the protocol gone
from the public page and there again after the next finalization. A unit test that finds a
protocol finalized again after its last send counted as not sent. A frontend unit test that finds the action on a final protocol without a
mark only, and the dialog before the request.
