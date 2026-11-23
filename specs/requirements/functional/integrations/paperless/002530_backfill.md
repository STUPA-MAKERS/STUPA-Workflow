---
id: "002530"
title: An admin can file the final documents that exist
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# An admin can file the final documents that exist

The admin page `Paperless` must have the action `Bestehende Dokumente ablegen`. The action must
start jobs for each final protocol, each decided Antrag and each Haushaltsplan in force that
has no filed document.

Reason: The integration can go on after years of use. The archive must then also get the
documents from before.

Test: A unit test starts the action with one final protocol without a filed document and one
with a filed document, and expects one job.
