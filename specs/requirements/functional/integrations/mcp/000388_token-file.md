---
id: "000388"
title: The MCP token file is private
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - mcp/
---

# The MCP token file is private

The MCP client stores its token per base URL in `~/.config/antragsplattform-mcp/` with the
directory mode 0700 and the file mode 0600.
