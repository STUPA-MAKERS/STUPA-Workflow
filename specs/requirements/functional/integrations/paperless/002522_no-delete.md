---
id: "002522"
title: The platform deletes no document in Paperless
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/paperless/test_client.py:test_each_request_carries_the_token_and_none_deletes"
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_a_protocol_that_is_final_again_replaces_its_documents"
implementation:
  - backend/app/modules/paperless/client.py
scope:
  - backend/app/
---

# The platform deletes no document in Paperless

The platform must not delete a document in Paperless. The platform must change only documents
that it filed.

Reason: Paperless is an archive of its own. The account of the platform needs no right to
delete there.

Test: A unit test of the client finds no request with the method DELETE.
