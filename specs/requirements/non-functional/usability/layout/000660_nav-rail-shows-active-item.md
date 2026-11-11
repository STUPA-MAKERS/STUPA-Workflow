---
id: "000660"
title: The navigation rail shows the active item
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/vendor/ui-kit/shell/src/nav-rail
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The navigation rail shows the active item

When the navigation rail does not have room for all items, it must scroll so that the active
item is fully in view. It must do this when the page loads and after each change of the route.

Reason: At a window height of 900 px the items Rechnungen and Tickets are below the edge of
the rail. On these pages no item shows as active, and the person cannot see where they are.

Test: A unit test of the rail gives it less height than its items need, makes the last item
active and expects the scroll position to show that item.
