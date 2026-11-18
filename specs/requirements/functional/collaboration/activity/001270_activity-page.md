---
id: "001270"
title: The activity page lists the events of the items of a person
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-17
implementation:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
scope:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
---

# The activity page lists the events of the items of a person

The page "Aktivität" at `/activity` must list the events of the items of the signed-in person,
newest first. The navigation must have its own entry for the page, in the rail and in the menu
"Mehr" of the phone. The page must not add a table of events. It must read the histories that
the modules already keep: the status timeline, the data versions and the comments of an Antrag,
the events and comments of a to-do card, the events and notes of a ticket, and the audit entries
of a meeting.

Reason: A person sees in one place what happened to the things they work on, without a second
record that can disagree with the history of the item.
