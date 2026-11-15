---
id: "001010"
title: A Gremium has an Info tab
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/gremien/test_gremium_info.py:test_empty_info_reads_for_member_and_view_all"
implementation:
  - backend/app/modules/gremien_overview/info.py
  - frontend/src/app/features/gremien/gremium-info
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.ts
scope:
  - backend/app/modules/gremien_overview
  - frontend/src/app/features/gremien
---

# A Gremium has an Info tab

The page of a Gremium in "Gremien" must have the tab "Info". The tab must show a Markdown text
and a list of labelled links of the Gremium. Everyone who sees the Gremium (000267, the gate
`can_view_gremium`) must be able to read the tab. The tab must be the first tab and must open
when the URL has no `?tab=`. The URL of the tab must be `?tab=info`.

Reason: Members need one place for the wiki, the chat groups and the standing facts of their
Gremium.

Test: A backend test of the read route for a member, a `gremium.view_all` holder and a stranger
(404). A component test of the tab order.
