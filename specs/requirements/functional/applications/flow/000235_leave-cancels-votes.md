---
id: "000235"
title: Leaving a vote state cancels its votes
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/voting
---

# Leaving a vote state cancels its votes

A transition without a branch, a forced status and a revert cancel votes. They cancel the
open votes of the Antrag and the drafts of the state that the Antrag leaves. A vote branch cancels nothing.
