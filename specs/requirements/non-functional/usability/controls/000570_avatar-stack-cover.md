---
id: "000570"
title: An avatar in a stack covers the one before it
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/lib/avatar/avatar-stack.component.scss
  - frontend/src/app/features/todos/card-tile/todo-card-tile.component.scss
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app/features/todos
---

# An avatar in a stack covers the one before it

In an avatar stack, each avatar must cover the part of the avatar before it that it overlaps. The
two avatars must not show through each other, also on a glass surface. A small gap must separate
the two avatars.

Reason: Translucent avatars on glass mix into one shape where they overlap, so the people are hard
to tell apart.

Test: A screenshot of a card with two assignees on a phone and on a wide screen shows the second
avatar in full and the cut of the first avatar.
