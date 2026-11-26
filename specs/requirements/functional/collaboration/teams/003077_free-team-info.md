---
id: "003077"
title: A free team has an Info tab
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-26
implementation: null
scope:
  - backend/app/modules/team_pages
  - frontend/src/app/features/gremien
  - mcp
---

# A free team has an Info tab

The page of a free team must have the tab Info. The tab must show one Markdown text and a list
of labelled links, in the same form as the Info tab of a Gremium. A member or a manager of the
team must be able to read it. Only a manager of the team (or an admin) must be able to change
it. A save must send the version that the editor read, and another version must give 409
`team_info_version_conflict`. A save must write an audit entry. The API must offer
`GET` and `PUT /api/teams/{id}/info`, and the MCP server must have a tool for each.

Reason: A team needs one place for its purpose, its contacts and its links.

Test: A backend test reads and saves the Info as a manager, gets 403 as a plain member and 409
for an old version. A frontend unit test shows the tab and the edit action for a manager only.
