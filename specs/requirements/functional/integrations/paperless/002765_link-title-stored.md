---
id: "002765"
title: A Paperless link keeps the title from the moment of the link
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/todos/test_paperless_links.py:test_an_outage_keeps_the_stored_title_and_the_other_hits"
  - "backend/tests/integration/modules/todos/test_paperless_links.py:test_a_card_links_a_document_and_the_document_is_stored_once"
  - "frontend/src/app/features/todos/linked-list/todo-linked-list.component.spec.ts:TodoLinkedListComponent"
implementation:
  - backend/app/modules/paperless/links.py
  - backend/app/modules/todos/links.py
  - frontend/src/app/features/todos/linked-list/todo-linked-list.component.html
scope:
  - backend/app/
  - frontend/src/app/
---

# A Paperless link keeps the title from the moment of the link

When a person links a Paperless document, the platform must store its title, its document type
and its date. `Verknüpft` and the graph must show the stored values and must not call Paperless.
A new link to the same document must update the stored values. A press on the row must open the
document in Paperless in a new tab.

Reason: An outage of Paperless must not slow a page of the platform (000176), and a list with
many links must load without a call for each row.

Test: A backend unit test links a document, lets Paperless fail and reads the link with its
stored title.
