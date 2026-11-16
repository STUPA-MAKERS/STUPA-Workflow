---
id: "000902"
title: A Wiederholungssitzung has its own quorum
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/livevote/test_quorum_present.py:test_a_repeat_meeting_uses_the_repeat_quorum"
  - "backend/tests/unit/modules/livevote/test_livevote_cov.py:test_gremium_repeat_quorum_percent"
implementation:
  - backend/app/modules/gremien/models.py
  - backend/app/modules/livevote/vote_build.py
  - backend/app/modules/livevote/service/votes.py
  - frontend/src/app/pages/admin/committees/gremium-dialog/gremium-dialog.component.html
scope:
  - backend/app/modules/gremien
  - backend/app/modules/admin
  - backend/app/modules/voting
  - backend/app/modules/livevote
  - frontend/src/app/pages/admin
---

# A Wiederholungssitzung has its own quorum

A Gremium must have the optional setting `repeatQuorumPercent`. A vote in a meeting of the kind
`repeat` (000903) must use this value in place of `quorumPercent`. Without a value the vote
must use `quorumPercent`.

Reason: The Organisationssatzung lowers the Beschlussfähigkeit of a Wiederholungssitzung from
40 % to 25 %.

Test: An integration test with a meeting of the kind `repeat`.
