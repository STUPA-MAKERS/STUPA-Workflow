---
id: "000633"
title: A note shows a state of the data, not a failed request
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A note shows a state of the data, not a failed request

An error note (`app-note` with `kind="error"`) must show only a state of the data that the
user can change on this view: a value that is not allowed, or a conflict between two records.
A request that fails (a load, a save, a delete, an upload) must show as a toast
(`NF/usability/controls/000401`), also when the request starts in a dialog. The dialog must
stay open after a failed request.

Reason: Verwaltung shows a failed save as a toast on most pages, but as a red note in the
dialogs of Dokument-Varianten, Übersetzungen, Gremien, Gremienrollen and the substitute
pool, and as a note on the page Benachrichtigungen.

Test: A unit test of each of these components makes the request fail and expects one error
toast and no `app-note` with `kind="error"`.
