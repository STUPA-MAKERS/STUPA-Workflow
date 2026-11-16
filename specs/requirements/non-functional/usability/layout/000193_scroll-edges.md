---
id: "000193"
title: A scroll edge fades, or cuts at a line
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.scss
  - frontend/vendor/ui-kit/src/styles/_frosted.scss
  - frontend/vendor/ui-kit/src/styles/list-detail.scss
  - frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.scss
  - frontend/vendor/ui-kit/src/lib/list-group/list-group.component.scss
  - frontend/vendor/ui-kit/src/lib/scroll-fade
  - frontend/vendor/ui-kit/src/styles/_scroll-fade.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - frontend/src/app/features/todos/card-detail
---

# A scroll edge fades, or cuts at a line

A scrolling pane must fade at its edges. At each edge of this table, the content must do what
the table says in place of the fade:

| Edge | What the content must do |
| --- | --- |
| A real line, for example a tab line on the phone | It cuts hard at that line. |
| The lower edge of a glass list head (000527) | It runs on under the line as a blur. The list under the head does not fade, and its rows run to the bottom edge of the screen. |
| The top edge of the screen, where the glass of a list head reaches it | The glass turns into the solid page colour at that edge over 48 px. This applies to every list head: the head of a list column on a wide screen, the search bar of a list on a phone, and a group head that carries the glass of the head. The sides of the glass keep their fade into the page colour. Where the head sticks below another bar, the glass does not fade at its top, because that bar is the edge. |
| The lower edge of the side sheet of a to-do card beside the board, on a wider screen | The details column runs to that edge and cuts hard there. Its upper end still fades. |
| The lower edge of the window below the work list of Start (000624) | The rows cut hard at that edge, and the panel fades at neither end. |

Reason: A fade shows that the content goes on. The edge of the screen and a tab line are real
lines, so a fade there hides rows for no gain. Rows under a glass head stay in view as a
blur, and at the top edge of the screen they would cut sharp, so the glass runs out into the
page colour there, as its sides do.

Test: Screenshots of a list with rows scrolled under the head (Verwaltung, Anträge) on a phone
and on a desktop width, in the light and the dark theme, and of an open to-do card with a long
details column on a desktop width.
