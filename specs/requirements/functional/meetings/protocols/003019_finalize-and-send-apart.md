---
id: "003019"
title: Finalize and send are two actions
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "backend/tests/integration/modules/protocol/test_protocol_send.py:test_finalize_sends_no_mail"
  - "backend/tests/integration/modules/protocol/test_protocol_send.py:test_send_mails_the_final_pdf"
  - "backend/tests/integration/modules/protocol/test_protocol_send.py:test_send_of_a_draft_is_refused"
  - "frontend/vendor/ui-kit/views/protocol/src/protocol-actions.util.spec.ts:sendFinal"
  - "frontend/src/app/features/meetings/protocol-bar/protocol-bar.component.spec.ts:sendFinal"
implementation:
  - backend/app/modules/protocol/service/finalize.py
  - backend/app/modules/protocol/router.py
  - backend/app/modules/protocol/service/common.py
  - mcp/antragsplattform_mcp/tools/meetings.py
  - frontend/src/app/features/meetings/meeting-session.service.ts
  - frontend/vendor/ui-kit/views/protocol/src/protocol-bar-view.component.ts
  - frontend/src/app/features/meetings/finalize-protocol-dialog/finalize-protocol-dialog.component.ts
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
  - mcp
---

# Finalize and send are two actions

The finalization of a protocol (000116) must render and store the PDF and make the protocol
final. It must not send a mail. The button and the dialog must say "Finalisieren", not
"Finalisieren & senden".

A person with `protocol.finalize` in the Gremium must be able to send a final protocol with
the action "Protokoll senden" (`POST /api/protocols/{id}/send`). The send must mail the stored
PDF to the recipients of 000358, with the variant rules of 000691. The send must ask first.
A protocol that is not final must answer 409 `protocol_not_final`. A protocol without a
recipient must answer 409 `protocol_no_recipients`. The send must set `sent_at` and must write
the audit entry `protocol_send` with the number of recipients.

A final protocol counts as sent only when `sent_at` is at or after `finalized_at`. Until then,
the meeting head must show "Protokoll final, nicht versandt", and the head action of a holder
of `protocol.finalize` must be "Senden". After the send, the head action must be the PDF again.

The person must be able to send a final protocol again. The confirmation of a repeat must
show the date of the last send. A protocol that goes back to draft (000983) and is finalized
again counts as not sent until the next send.

Reason: The keeper wants to check the final PDF before it goes to the Gremium and to the
mailing list, and to choose the moment of the mail. One button for both steps sent the mail
at once.

Test: An integration test that finalizes a protocol and finds no mail job, then sends it and
finds one mail job with the PDF and `sent_at`. One that sends a draft and gets 409
`protocol_not_final`. A frontend unit test that finds "Senden" as the head action of a final
protocol that was not sent, and the PDF after the send.
