---
id: "002867"
title: A change of a Bestellung names its version
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
---

# A change of a Bestellung names its version

A Bestellung must have a `version` that each write raises by one. A change must name the version
that the person read. The server must answer 409 `order_version_conflict` when a different
version is current.

Reason: Two persons can edit the same Bestellung. Without the check the later save deletes the
change of the first person without a notice.

Test: A backend unit test sends two changes with the same version and expects 409 for the
second.
