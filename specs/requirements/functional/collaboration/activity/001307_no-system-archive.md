---
id: "001307"
title: The automatic archive of a to-do card is not an activity
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - backend/app/modules/activity
scope:
  - backend/app/modules/activity
---

# The automatic archive of a to-do card is not an activity

The activity page must not show the event "archived" of a to-do card when the system wrote it
(no actor, the nightly archive cron). The event must not light the dot "neu" in the
navigation. An archive that a person does stays an activity.

The event stays in the timeline of the card.

Reason: The cron archives every done card after the limit of its board. These rows say
nothing new to the person and only light the dot.
