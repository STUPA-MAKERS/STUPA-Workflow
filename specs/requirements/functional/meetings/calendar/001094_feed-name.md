---
id: "001094"
title: A calendar feed is named by the short name
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/calendar/test_calendar_router.py:test_feed_returns_ics_with_meeting"
  - "backend/tests/unit/modules/admin/test_page_head.py:test_the_short_name_and_its_file_name_part"
implementation:
  - backend/app/modules/calendar/router.py
  - backend/app/modules/calendar/public_router.py
  - backend/app/modules/site_config/names.py
scope:
  - backend/app/modules/calendar
  - backend/app/modules/site_config
---

# A calendar feed is named by the short name

The personal feed must be named "<Kurzname> — Sitzungen" and the public feed
"<Kurzname> — Öffentlicher Kalender", with the short name of the active branding. The file
names must start with the short name in lower case ASCII. An empty short name must give
"STUPA".

Reason: A calendar app shows the feed name in a narrow list. A fixed name is wrong for
every other branding.

Test: A unit test reads the name and the file name of the personal feed.
