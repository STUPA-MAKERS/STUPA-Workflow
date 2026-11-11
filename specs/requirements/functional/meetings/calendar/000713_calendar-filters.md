---
id: "000713"
title: The Kalender filters by kind and by Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/src/app/features
---

# The Kalender filters by kind and by Gremium

The Kalender must have a filter for the kind of entry and a filter for the Gremium, in the
filter controls that the lists of the app use. The Gremium filter must keep the entries without a
Gremium only when no Gremium is picked.

Reason: A member of several Gremien needs the dates of one Gremium alone.

Test: A frontend unit test picks a Gremium and checks that a private Termin is not shown.
