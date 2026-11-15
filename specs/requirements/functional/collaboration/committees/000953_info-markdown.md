---
id: "000953"
title: The Info text is sanitized Markdown
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/gremien/test_gremium_info.py:test_long_text_gives_422"
implementation:
  - backend/app/modules/gremien_overview/schemas.py
  - frontend/src/app/features/gremien/gremium-info
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
