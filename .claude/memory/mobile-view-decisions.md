---
name: mobile-view-decisions
description: "Binding mobile/responsive rules: 768px breakpoint, additive media queries only, phone bottom bar + Mehr sheet, bottom inset for fixed elements, footer only on start and public pages, PWA bar colours"
metadata:
  node_type: memory
  type: project
---

The rules are specs in `specs/` of the STUPA-Workflow repository. Read the spec, not this
file:

- `NF/usability/layout/000194` The phone layout starts below 768 px
- `NF/usability/layout/000406` The phone layout does not change the desktop
- `NF/usability/layout/000195` The phone bottom bar is fixed
- `NF/usability/layout/000407` Mehr and Suche are always in reach
- `NF/usability/layout/000408` Fixed bottom elements sit above the bottom bar
- `NF/usability/layout/000409` The phone shows one pane and card tables
- `NF/usability/layout/000196` The phone opens pickers as bottom sheets
- `NF/usability/layout/000199` The footer shows only on start and public pages
- `NF/usability/controls/000410` A tap tints the whole tile
- `NF/compatibility/pwa/000220` Zoom is blocked only in the installed app
- `NF/compatibility/pwa/000411` The status bar follows the theme
- `NF/compatibility/pwa/000221` The Android navigation bar has the manifest colour
