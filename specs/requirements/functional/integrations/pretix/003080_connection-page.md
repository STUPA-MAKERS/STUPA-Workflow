---
id: "003080"
title: An admin connects one pretix organizer
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# An admin connects one pretix organizer

The admin page `Pretix` (`/admin/pretix`) must hold the address of a pretix instance, the short
name of one organizer and an API token of a team of that organizer. The page must have a button
that tests the connection and shows the result. The page must need the permission
`admin.pretix` (`Pretix verwalten`). Each save must write an audit entry without the token.

Reason: The integration works with each pretix instance, self-hosted or hosted. One organizer
holds the shops of one student government, and one team token gives the rights of the platform
in pretix.

Test: A backend unit test saves a connection without the permission and expects 403, and tests
a connection against a fake pretix.
