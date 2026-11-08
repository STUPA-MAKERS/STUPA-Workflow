---
id: "000542"
title: An Antrag can have one Vorgänger
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# An Antrag can have one Vorgänger

An Antrag must have at most one Vorgänger. A Vorgänger must be able to have more than one
Folgeantrag. An Antrag must not be its own Vorgänger, and a chain of Vorgänger links must not
form a cycle. When an Antrag is deleted, its links must be deleted with it. The Folgeanträge of
that Antrag must stay.

Reason: A Folgeantrag continues one earlier Antrag, for example the same event in the next
year. One Vorgänger keeps the chain a line that the detail can show.

Test: Unit tests of the link service: a second Vorgänger, a self link and a cycle fail with
422, and a delete removes the link but not the Folgeantrag.
