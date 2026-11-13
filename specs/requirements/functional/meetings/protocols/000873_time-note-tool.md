---
id: "000873"
title: A toolbar tool inserts a time note
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation: null
scope:
  - frontend/vendor/ui-kit/markdown-editor
  - frontend/src/app/features/meetings
  - frontend/src/app/shared/markdown
---

# A toolbar tool inserts a time note

The format bar of the protocol editor must have a tool "Anmerkung". The tool must insert a time
note (000872) with the current time in Europe/Berlin on a new line at the caret and put the
caret in its text. The time must stay editable. The editor and the read view of the app must
show a note in the same style as the PDF.

Reason: The person who writes the protocol records an event with one click while the Sitzung
continues.

Test: Component test of the editor: the tool inserts the line with the time, and the caret is
in the text.
