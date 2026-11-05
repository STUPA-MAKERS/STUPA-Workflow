---
id: "000345"
title: Meeting rights are per Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/livevote
---

# Meeting rights are per Gremium

`session.manage` in the Gremium of the meeting manages it. The assigned protokollant and
`protocol.write` can write status, agenda and protocol. `vote.manage` adds the votes. There is
no global meeting key except `meeting.view_all` to read.
