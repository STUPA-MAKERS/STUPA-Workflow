---
id: "000524"
title: The protocol PDF is tagged as PDF/UA-1
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - typst/typst_service
  - typst/template
---

# The protocol PDF is tagged as PDF/UA-1

The typst service must make the protocol PDF with `--pdf-standard ua-1`. The PDF must have
a title and a language.

Reason: A protocol is public, so § 10 L-BGG applies to it. A tagged PDF lets a screen reader
read the structure.
