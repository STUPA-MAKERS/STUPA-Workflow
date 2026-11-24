---
id: "002922"
title: An MCP link tool names a Paperless end by its document number
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "mcp/antragsplattform_mcp/tests/test_paperless_links.py:test_a_paperless_end_goes_by_its_number"
implementation:
  - mcp/antragsplattform_mcp/tools/links.py
  - mcp/antragsplattform_mcp/schemas.py
scope:
  - mcp/
---

# An MCP link tool names a Paperless end by its document number

The schemas of the link tools must name the kind `paperless`. A tool must take a Paperless end
as the number of the document in Paperless, and must not ask for the internal id of its row. A
link row and a search hit with a Paperless end must give the document number too. The tool
`paperless_document_address` must read the address of the filed document of an element.

Reason: An agent knows a document by the number that Paperless shows. The row id is internal.

Test: An MCP unit test adds a link with a document number and checks the body of the request.
