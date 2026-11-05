---
id: "000295"
title: The hash input is canonical
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/audit
---

# The hash input is canonical

The hash covers a canonical JSON form: sorted keys, compact separators and the time in UTC.
A value that is not JSON native fails the write.

Reason: A change of the canonical form breaks the check of every older entry.
