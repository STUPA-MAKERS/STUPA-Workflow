---
id: "000419"
title: A Gremium delete deletes its meetings
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/admin
  - backend/app/modules/livevote
---

# A Gremium delete deletes its meetings

The delete of a Gremium runs the meeting delete for each meeting. Votes without a meeting
stay. An open vote refuses the delete with 409 `open_vote`.
