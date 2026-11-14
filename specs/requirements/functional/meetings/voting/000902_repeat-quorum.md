---
id: "000902"
title: A Wiederholungssitzung has its own quorum
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
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
