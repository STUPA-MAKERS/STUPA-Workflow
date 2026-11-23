---
id: "001201"
title: The MCP leaves out a closed list of functions
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "mcp/antragsplattform_mcp/tests/test_route_parity.py:test_exclusions_are_routes"
implementation:
  - mcp/antragsplattform_mcp/tests/test_route_parity.py
scope:
  - mcp/
---

# The MCP leaves out a closed list of functions

The MCP server must not have a tool for these functions:

- casting a ballot (F/integrations/mcp/000386), also for a guest of a public meeting
- the human-only permissions of F/integrations/mcp/000462: backups, account merge and the
  revoke of the groups of an account
- a write of a membership or a role assignment (F/administration/accounts/000154)
- the objection (Einspruch) against an Umlaufverfahren, because only a person objects
- the run of a privacy erasure: the erasure of an e-mail address, of a principal and the run
  of an erasure request, because it cannot be undone
- the change of the login lifetime, because the server refuses it to every agent token
- the Paperless connection, its actions and the address of a filed document, because no
  OAuth scope carries the permissions `admin.paperless` and `paperless.use`
- the Postfach of a ticket Bereich and its connection test, because no OAuth scope carries
  the permission `admin.ticket_mail`
- the login, logout, OAuth and consent routes, the MCP package download and the ALTCHA
  challenge
- the WebSocket channels with the tile read of a live ping, the ICS feeds with their token
  and the public pages without a login
- the removal of the event data of a card, because the route always refuses it
- the branding images, the manifest, the page head, the avatars and the health check
- the web push routes of a browser: the public key, the subscription of a device and the
  action of a push button, because only a browser and its service worker use them

Reason: Each function acts for a person, cannot be undone, or exists only for a browser.

Test: The exclusion list of the parity test of F/integrations/mcp/001200 holds exactly these
routes.
