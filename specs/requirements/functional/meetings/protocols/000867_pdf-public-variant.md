---
id: "000867"
title: The PDF of a non-public TOP stays internal
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation: null
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/public-protocols
---

# The PDF of a non-public TOP stays internal

The public PDF (000355) and the public protocol page must hold only the embedded PDFs of
public texts. An embedded PDF of a non-public TOP must not be an Anlage of the public PDF, and
its public download must answer 404. The public PDF must number its own Anlagen from 1.

Reason: A non-public TOP often treats a document with personal or internal data.

Test: Unit tests of the public render input and of the public PDF download route.
