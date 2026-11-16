---
id: "001232"
title: The MCP server presents itself as workflow
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/auth/test_oauth_cov.py:test_mcp_config_success"
  - "backend/tests/unit/modules/auth/test_oauth_cov.py:test_mcp_package_streams_tarball"
  - "frontend/src/app/pages/account/grants.component.spec.ts:AccountGrantsComponent"
implementation:
  - mcp/antragsplattform_mcp/server.py
  - backend/app/modules/auth/mcp_router.py
  - frontend/src/app/pages/account/grants.component.ts
scope:
  - mcp/
  - backend/app/modules/auth
  - frontend/src/app/pages/account
---

# The MCP server presents itself as workflow

The MCP server must have the name `workflow`, and its instructions to an agent must name the
platform "STUPA Workflow". The ready-made client entry must use the key `workflow`, and the
package download must be the file `workflow-mcp.tar.gz`. The command `antragsplattform-mcp`,
the variables `ANTRAGSPLATTFORM_URL` and `ANTRAGSPLATTFORM_SCOPE` and the OAuth client id
`antragsplattform-mcp` must stay.

Reason: An agent and its user see the name of the server and of the download. The package is
installed before it reaches a platform, so it cannot read the branding. The command, the
variables and the client id stay, because a change stops every installed server and every
granted login.

Test: Unit tests check the client entry and the name of the download.
