---
id: "003078"
title: The edit action of a filled Info sits under it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-26
implementation:
  - frontend/src/app/features/gremien/gremium-info
scope:
  - frontend/src/app/features/gremien
---

# The edit action of a filled Info sits under it

When an Info has a text or a link, an editor must find its edit action under the Info, after the
line of the last change, centred. The action must be a small text button with the pencil icon
and the label "Bearbeiten" in a button group, in the same form as "Frühere Sitzungen laden" of the meetings list.
The Info of a Gremium and the Info of a free team (003077) must use the same component, so both
show the action in the same place. An empty Info keeps its empty state with the action
"Info bearbeiten" (001015).

Reason: The text of the Info comes first, and a large button above it takes the place of the
content.

Test: A component test finds the action "Bearbeiten" after the line of the last change, and no
action for a reader.
