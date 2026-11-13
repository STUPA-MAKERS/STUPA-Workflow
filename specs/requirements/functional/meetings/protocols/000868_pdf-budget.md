---
id: "000868"
title: A protocol holds at most 20 Anlagen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation: null
scope:
  - backend/app/modules/protocol
  - backend/app/modules/media
---

# A protocol holds at most 20 Anlagen

A protocol PDF must hold at most 20 Anlagen and at most 300 Anlage pages in total. An embedded
PDF over this limit, or one that is missing, must not be an Anlage. Its place must print
`Anlage nicht eingebunden: <file name>`. An embedded PDF must never make the render fail.

Reason: The typst service has fixed memory and time. A finalize must not stop because of one
document.

Test: Unit test of the render input: the 21st PDF is left out and its place has the text.
