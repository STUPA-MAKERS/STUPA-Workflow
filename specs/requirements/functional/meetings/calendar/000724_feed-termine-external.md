---
id: "000724"
title: The personal feed holds Termine and external entries
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
---

# The personal feed holds Termine and external entries

The ICS feed of a person must also hold the Termine that the person reads and the entries of
the external calendars that the person reads. The answer of the person must be the participation
status of a Termin in the feed. The feed must hold the due cards under its own rule of the
assigned cards.

Reason: A person who subscribes the feed has one calendar for all dates of the platform.

Test: A backend unit test reads a Termin and an external entry from the feed of an invited
person and not from the feed of a third person.
