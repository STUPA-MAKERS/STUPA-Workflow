---
id: "002844"
title: A link to Paperless names the address for links
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/unit/modules/paperless/test_link_address.py:test_a_link_names_the_address_for_links"
  - "backend/tests/unit/modules/paperless/test_link_address.py:test_a_link_without_an_address_for_links_names_the_server_address"
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_the_entry_names_the_address_for_links_and_the_calls_go_to_the_server_address"
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_the_address_for_links_changes_without_the_token"
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_the_address_for_links_needs_http_or_https"
  - "frontend/src/app/pages/admin/paperless/paperless.component.spec.ts:PaperlessComponent"
implementation:
  - backend/app/modules/paperless/client.py
  - backend/app/modules/paperless/connection.py
  - backend/app/modules/paperless/filings.py
  - backend/app/modules/paperless/links.py
  - backend/app/modules/tickets/paperless.py
  - frontend/src/app/pages/admin/paperless
scope:
  - backend/app/modules/paperless
  - backend/app/modules/tickets
  - frontend/src/app/pages/admin/paperless
---

# A link to Paperless names the address for links

The Paperless connection must have the optional field `Adresse für Links` beside the address.
Each link that a browser opens must name the address for links, or the address when the field
is empty: the entry `In Paperless öffnen`, a linked document, a filed ticket file and a filed
document in an erasure or an export. The server must call the API of Paperless only on the
address. The save must accept for the address for links only an absolute `http` or `https`
address and must answer 422 `paperless_link_address_invalid` for a different value. The
allowlist (002514) and the token rule (002813) must not apply to the address for links.

Reason: The server often reaches Paperless on an internal address with a token, and a person
opens Paperless on its public name after a login, so one address cannot serve both. The server
never calls the address for links, so it cannot send the token to it.

Test: A unit test builds a link with and without the address for links and expects the address
for links and the address. An integration test reads the entry `In Paperless öffnen` with an
address for links, expects the address for links in the link and the API calls on the address,
and changes the address for links without the token.
