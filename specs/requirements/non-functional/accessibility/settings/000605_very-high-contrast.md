---
id: "000605"
title: Very high contrast shows the app in four colours
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:veryHighContrast"
  - "frontend/src/app/shared/very-high-contrast.styles.spec.ts:surfaceEdges"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
  - frontend/vendor/ui-kit/src/lib/switch/switch.component.scss
  - frontend/vendor/ui-kit/src/lib/seg-bar/seg-bar.component.scss
  - frontend/src/app/pages/budget/budget-pie.component.scss
  - frontend/src/app/pages/budget/budget-sunburst.component.scss
  - frontend/src/app/features/help/help-menu/help-menu.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Very high contrast shows the app in four colours

With the switch "Hoher Kontrast" on (000593), every page must use only these colours:
black `#000000` for every background, white `#ffffff` for text, icons and edges, yellow
`#ffff00` for the controls of 000598, and light red `#ff8a8a` for error texts and error edges.
A destructive button stays dark red on yellow (000598). Every surface (card, bar, sheet,
menu, dialog, popover, table) must have a 2 px white edge, because no shade or tint sets it
apart. In a grouped list each row must have the edge, not the group, and the rows must sit
apart. A card and a column of a board must have the edge. There must be no shadow, no gradient, no glass, no tint and no accent colour of the
branding. A head that stays in place over a list must be solid black, so that no row shows
through it, and must end in a white line while rows are under it. The edge of a surface and the line at
the end of a scroll area must stay in view at every scroll position: content that scrolls inside
the surface or past the line, a head that stays in place and a control under the pointer must
not paint over them. This holds on every side, also where content touches the edge, as in a
sheet, a comment log or a table. A link must be yellow and underlined. A colour that marks a state (a status, a
state flag, a label of a card, a calendar entry, a budget bar) must turn into white text with
a white edge, so that the text or the icon tells the state. A chart must draw its parts in the
four colours and must separate them with a 2 px black edge. A disabled control must have white
text and a dashed white edge without a fill. Images, avatars and logos stay as they are. This
applies in both themes.

Reason: A person with very low vision, or one who reads a beamer in a bright room, needs the
highest contrast (21:1 for text) and few colours that each have one meaning.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts`.
