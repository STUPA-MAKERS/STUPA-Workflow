---
id: "000997"
title: A protocol counts as sent only when its mail went out
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "backend/tests/unit/modules/protocol/test_protocol_service.py:test_finalize_without_a_recipient_marks_no_send"
  - "backend/tests/unit/worker/test_protocol_worker.py:test_render_protocol_success_finalizes"
  - "frontend/src/app/features/meetings/protocol-bar/protocol-bar.component.spec.ts:ProtocolBarComponent"
implementation:
  - backend/app/modules/protocol/service.py
  - backend/app/modules/protocol/public.py
  - backend/app/modules/meetings/protocol_models.py
  - backend/migrations/versions/a7d3e91f5b20_protocol_finalized_at.py
  - frontend/src/app/features/meetings/protocol-bar/protocol-bar.component.ts
scope:
  - backend/app/modules/protocol
  - backend/app/modules/meetings
  - frontend/src/app/features/meetings
---

# A protocol counts as sent only when its mail went out

The finalization of a protocol must store its moment as `finalized_at`. It must set `sent_at`
only when the mail of the final protocol went to the mail queue. Without a recipient, or
without a mail queue, `sent_at` must stay empty. The public protocols page must show
`finalized_at` as the date of the finalization.

The meeting head must show a final protocol as "Protokoll final" only with `sent_at`. Without
it, the head must say that the protocol was not sent, because there are no recipients (ui-kit:001304).

A protocol that was final before this rule keeps its `sent_at` and gets the same value as
`finalized_at`.

Reason: A Gremium without members with an e-mail address and without extra addresses gets no
mail. The page said "versandt", so the keeper did not send the protocol by hand.
