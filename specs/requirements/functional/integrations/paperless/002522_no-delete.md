---
id: "002522"
title: The platform deletes no document in Paperless
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
---

# The platform deletes no document in Paperless

The platform must not delete a document in Paperless. The platform must change only documents
that it filed.

Reason: Paperless is an archive of its own. The account of the platform needs no right to
delete there.

Test: A unit test of the client finds no request with the method DELETE.
