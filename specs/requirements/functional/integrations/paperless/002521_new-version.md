---
id: "002521"
title: A new version becomes a new document
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# A new version becomes a new document

When an element that has a filed document gets a new final file, the platform must file the
new file as a new document. The platform must give the document before it the tag `Ersetzt`.

Reason: A protocol can go back to the draft and become final again. The archive must show
which document is in force.

Test: A unit test finalizes a protocol two times and expects two documents and the tag on the
first.
