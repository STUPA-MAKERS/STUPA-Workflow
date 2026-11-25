---
id: "003087"
title: A person creates the shop of an Event in pretix
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# A person creates the shop of an Event in pretix

The admin page `Pretix` must have the field `Vorlage`: one pretix event of the organizer. An Event
without a link must have the action `Shop in Pretix anlegen` for a person who writes the Event
and holds `pretix.use`. The action must make a copy of the template in pretix with the name, the
start, the end and the place of the Event, and link the copy to the Event (003083). The copy
must not be live. The action must not change the template or a different pretix event.

Reason: The shops of a student government repeat their products, prices and settings, so a
copy of a template is the quick start. A person checks the copy in pretix before the shop goes
live.

Test: A backend unit test creates a shop with a fake pretix, reads the clone call with the data
of the Event and `live: false`, and reads the link.
