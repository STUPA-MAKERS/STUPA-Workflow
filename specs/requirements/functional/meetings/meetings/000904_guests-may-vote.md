---
id: "000904"
title: Guest ballots are a Gremium setting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/livevote/test_public_meeting.py:test_guest_mode_follows_the_switch_of_the_gremium"
  - "backend/tests/unit/modules/livevote/test_public_meeting_lead_unit.py:test_guest_ballot_needs_the_switch_and_no_quorum"
  - "backend/tests/unit/modules/admin/test_admin_service_cov.py:test_update_gremium_takes_the_ballot_from_guests"
implementation:
  - backend/app/modules/gremien/models.py
  - backend/app/modules/livevote/service/lifecycle.py
  - backend/app/modules/admin/service/gremien.py
  - frontend/src/app/features/meetings/public-join/public-join-settings.component.html
scope:
  - backend/app/modules/gremien
  - backend/app/modules/admin
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - frontend/src/app/pages/admin
---

# Guest ballots are a Gremium setting

A Gremium must have the switch `guestsMayVote`, and a new Gremium must start with the value
off. While the switch is off, the server must refuse the guest mode "Gäste dürfen abstimmen"
with 422 `guests_vote_off`. A new meeting must then start in the mode "nur zuschauen".

Reason: The Geschäftsordnung gives guests no vote. Only a Gremium that decides it differently
lets guests vote.

Test: An integration test that sets the guest mode of a meeting.
