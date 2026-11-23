---
id: "002527"
title: Two colons open the Paperless search in a protocol text
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - frontend/src/app/
  - backend/app/
---

# Two colons open the Paperless search in a protocol text

In each Markdown text of a protocol (000862), the editor must open the Paperless search (002534)
when a person with `paperless.use` types `::` at the start of a word. The editor must remove
the `::` when the search opens. Without the permission or with the integration off, `::` must
stay plain text.

Reason: A person inserts a document of the archive at the place where the Sitzung treats it,
without a download and an upload.

Test: A unit test of the editor types `::` with and without the permission.
