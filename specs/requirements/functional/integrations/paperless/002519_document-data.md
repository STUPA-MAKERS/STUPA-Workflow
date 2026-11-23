---
id: "002519"
title: A filed document carries type, date, Gremium and link
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_a_final_protocol_is_filed_once_in_both_variants"
  - "backend/tests/unit/modules/paperless/test_client.py:test_set_link_keeps_the_other_custom_fields"
implementation:
  - backend/app/modules/paperless_filing/files.py
  - backend/app/modules/paperless_filing/runner.py
scope:
  - backend/app/
  - frontend/src/app/
---

# A filed document carries type, date, Gremium and link

The platform must give each document that it files these data:

- the title of the element,
- the date of the event that filed it,
- the document type `Protokoll`, `Antrag` or `Haushaltsplan`,
- one tag with the name of the Gremium, when the element has a Gremium,
- the custom field `Plattform` with the URL of the element in the platform.

The platform must create a document type, a tag or the custom field that Paperless does not
have.

Reason: A person in Paperless must find a document by its kind and its Gremium, and must reach
its element in the platform with one click.

Test: A unit test of the filing job expects these data in the request to Paperless.
