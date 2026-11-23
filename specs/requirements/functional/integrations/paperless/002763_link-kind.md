---
id: "002763"
title: A Paperless document is a kind of link end
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/todos/test_paperless_links.py:test_a_card_links_a_document_and_the_document_is_stored_once"
  - "backend/tests/integration/modules/todos/test_paperless_links.py:test_the_row_id_names_the_document_number"
implementation:
  - backend/app/modules/paperless/links.py
  - backend/app/modules/paperless/models.py
  - backend/app/modules/todos/link_service.py
  - backend/app/modules/todos/models.py
scope:
  - backend/app/
  - frontend/src/app/
---

# A Paperless document is a kind of link end

A link (F/collaboration/links/001400) must be able to connect an element of the platform with a
Paperless document. The kind must be `paperless`, with the name `Paperless-Dokument`, and it
must be the last kind in the order of 001400. Two Paperless documents must not link to each
other. The platform must store each linked document once, with its number in Paperless, and the
link must point to that row (001402).

Reason: A contract or a notice in the archive belongs to an Antrag, a TOP or a Buchung. The link
shows that relation without a copy of the file.

Test: A backend unit test links an Antrag to a Paperless document, refuses a link between two
Paperless documents and stores the same document once for two links.
