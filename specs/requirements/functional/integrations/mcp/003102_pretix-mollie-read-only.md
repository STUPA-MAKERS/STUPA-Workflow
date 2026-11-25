---
id: "003102"
title: A token reads the pretix and Mollie sums only through the Event
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
  - mcp/
---
# A token reads the pretix and Mollie sums only through the Event

An MCP tool that reads an Event must give the sums of 003084 and 003096 when the person reads
the Event. No OAuth scope must give the link of 003083, the create of 003087 or a call to pretix
or Mollie.

Reason: An agent needs the numbers of an Event for a report. A link or a new shop acts in an
external system, and a person does this in the UI.

Test: A backend unit test reads an Event with a token and finds the sums, and gets 403 for the
link with a token.
