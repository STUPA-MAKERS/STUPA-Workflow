---
id: "000723"
title: External entries are plain and read-only
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/app/modules/calendar/external_feed.py
  - backend/app/modules/calendar/external.py
scope:
  - backend/app/modules/calendar
---

# External entries are plain and read-only

The platform must store of an external entry only the title, the start, the end, the place and
the description, as plain text. It must not store organisers, attendees or attachments. A
recurring entry must show at each of its dates in a window of 12 months back and 24 months
ahead. A person must not be able to change an external entry in the platform.

Reason: A foreign feed can hold mail addresses of third persons and markup. The platform shows
dates, it does not mirror the source.

Test: A backend unit test imports an entry with attendees and HTML and reads plain text without
an address. A backend unit test imports a weekly entry and reads it on two dates.
