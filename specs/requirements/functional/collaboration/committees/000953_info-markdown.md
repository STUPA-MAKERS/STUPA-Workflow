---
id: "000953"
title: The Info text is sanitized Markdown
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation: null
scope:
  - backend/app/modules/gremien_overview
  - frontend/src/app/features/gremien
---

# The Info text is sanitized Markdown

The Info text must be Markdown of at most 20 000 characters. The tab must render it with the
sanitizing Markdown renderer of the app, the same as a to-do card. The editor must be the
Markdown field of the app with a preview. The text must not hold raw HTML.

Reason: One renderer keeps one sanitizer, so a Gremium text cannot carry a script.

Test: A component test that a `<script>` in the text renders as text.
