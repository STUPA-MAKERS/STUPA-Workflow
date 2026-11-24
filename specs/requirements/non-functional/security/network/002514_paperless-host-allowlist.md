---
id: "002514"
title: The Paperless address needs a host from the deploy settings
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_a_host_outside_the_allowlist_is_refused"
  - "backend/tests/unit/modules/paperless/test_client.py:test_a_host_outside_the_allowlist_gets_no_request"
  - "backend/tests/unit/modules/paperless/test_client.py:test_an_error_answer_is_a_cause_code"
implementation:
  - backend/app/modules/paperless/client.py
  - backend/app/modules/paperless/connection.py
  - backend/app/settings.py
scope:
  - backend/app/
---

# The Paperless address needs a host from the deploy settings

The deploy setting `PAPERLESS_HOST_ALLOWLIST` names the hosts that the Paperless address can
have. The save of an address with a different host must answer 422 `paperless_host_not_allowed`.
With an empty list the save must refuse each address. The client must not follow a redirect.

Reason: Paperless often runs in the internal network. An address that an admin sets freely
lets the server call each internal host.

Test: A unit test saves an address whose host is not in the list and expects 422.
