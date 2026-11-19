---
id: "001500"
title: A list title starts on the edge of the search bar
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/lib/page-header/page-header.component.spec.ts:PageHeaderComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/page-header
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A list title starts on the edge of the search bar

On a wide screen, the title of a list column must start on the start edge of the search bar
and of the filter chips below it. The title keeps its size (28px). On a phone the title keeps
its small inset (4px).

This applies to every list column with a pane header (Anträge, Sitzungen, Abstimmungen,
Rechnungen, Buchungen, Tickets, Aktivität, Kalender, Gremien, Aufgaben, Haushalt, Verwaltung).

Reason: The title was inset 16px like the text of the rows. The search bar and the chips start
on the edge of the column, so the title stood a step to the right of them and looked
misaligned.

Test: A unit test of the page header reads its style and expects the start inset of a pane
header to be 0 when the page sets no `--ph-inset`.
