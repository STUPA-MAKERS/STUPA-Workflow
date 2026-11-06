---
id: "000345"
title: Meeting rights are per Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/livevote
---

# Meeting rights are per Gremium

`session.manage` in the Gremium of the meeting must manage it. The assigned protokollant and
`protocol.write` must be able to write status, agenda and protocol. `vote.manage` must add the
votes.
