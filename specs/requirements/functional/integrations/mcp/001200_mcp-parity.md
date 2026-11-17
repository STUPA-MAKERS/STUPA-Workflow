---
id: "001200"
title: The MCP server has a tool for every app function
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "mcp/antragsplattform_mcp/tests/test_route_parity.py:test_route_has_tool_or_exclusion"
  - "mcp/antragsplattform_mcp/tests/test_todo_card_parts.py:test_checklist_tools_add_tick_and_remove_a_subtask"
implementation:
  - mcp/antragsplattform_mcp/tools
scope:
  - mcp/
  - backend/app/modules
---

# The MCP server has a tool for every app function

The MCP server must have a tool for every API route that a page of the app uses. A route that
F/integrations/mcp/001201 names must not have a tool. A change that adds an API route must add
its tool or a line in F/integrations/mcp/001201 in the same pull request.

Reason: An agent works on the platform as the logged-in person and needs the same functions as
the page. Without the rule, the MCP falls behind with every new feature.

Test: An MCP test reads every route of the backend routers and fails for a route that no tool
calls and that the exclusion list does not name.
