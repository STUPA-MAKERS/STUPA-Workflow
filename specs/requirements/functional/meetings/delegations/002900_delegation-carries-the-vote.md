---
id: "002900"
title: A delegation always transfers the voting right
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/unit/modules/delegations/test_delegations_service_cov.py:test_create_always_carries_the_vote"
  - "frontend/src/app/features/meetings/delegation-dialog/delegation-dialog.component.spec.ts:DelegationDialogComponent"
implementation:
  - backend/app/modules/delegations/service.py
  - backend/app/modules/delegations/schemas.py
  - frontend/src/app/features/meetings/delegation-dialog/delegation-dialog.component.ts
  - frontend/src/app/features/meetings/lead-substitute-dialog/lead-substitute-dialog.component.ts
scope:
  - backend/app/modules/delegations
  - frontend/src/app/features/meetings
  - mcp/antragsplattform_mcp
---

# A delegation always transfers the voting right

Every delegation must transfer the voting right of the delegator to the delegate. This applies to
a delegation of the member and to a substitution that the meeting lead enters. The API must not
take a choice for the voting right. The dialogs must not show a switch for it.

Reason: A Vertretung without the Stimmrecht has no use in the Gremium, and a switch for it only
causes wrong delegations.

Test: A unit test that creates a delegation and finds `delegateVoting` true.
