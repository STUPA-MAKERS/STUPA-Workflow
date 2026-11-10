---
id: "000639"
title: The folder of an admin page has the name of its route
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/pages/admin
---

# The folder of an admin page has the name of its route

The component of an admin route must be in the folder `pages/admin/<segment>`, where
`<segment>` is the first path segment of the route below `/admin`. A route that shows the
component of another admin page or of another feature has no folder of its own. A folder
that holds parts for more than one page must have a name that says what the parts are.

Reason: Webhooks are in `config`, the route `committees` is in `gremien`, and the route
`flow` is in `flow-editor`, so the folder cannot be found from the URL.

Test: `frontend/src/app/pages/admin/admin-frame/admin-pages.spec.ts`: for each child route
of `/admin` with a component below `pages/admin`, the import path starts with the folder of
the route segment.
