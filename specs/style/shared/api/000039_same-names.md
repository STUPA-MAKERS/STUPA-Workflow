---
id: "000039"
title: Field names are the same in frontend and backend
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/
  - frontend/src/app/core/api/
  - mcp/
scope:
  - backend/app/
  - frontend/src/app/core/api/
  - mcp/
---

# Field names are the same in frontend and backend

Field, header and cookie names must be identical in the frontend and the backend. JSON uses
camelCase. Do not add a field in the frontend that the backend does not send.

Reason: Both sides compile with a wrong name, and then fail silently at runtime.
