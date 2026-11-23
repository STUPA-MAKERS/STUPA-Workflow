---
id: "002763"
title: A Paperless document is a kind of link end
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
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
