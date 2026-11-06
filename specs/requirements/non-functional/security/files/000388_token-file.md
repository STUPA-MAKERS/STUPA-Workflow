---
id: "000388"
title: The MCP token file is private
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - mcp/
scope:
  - mcp/
---

# The MCP token file is private

The MCP client must store its token per base URL in `~/.config/antragsplattform-mcp/` with the
directory mode 0700 and the file mode 0600.
