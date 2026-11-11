---
id: "000683"
title: The deployment view shows the services of the compose stack
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "backend/tests/unit/scripts/test_build_uml.py:test_deployment_view_has_each_service"
implementation:
  - scripts/build_uml.py
  - specs/uml/deployment.json
scope:
  - specs/
  - scripts/
  - deploy/docker-compose.yml
---

# The deployment view shows the services of the compose stack

`deployment.json` must hold one element for each service of `deploy/docker-compose.yml`. Each
element must have its `image` or the path of its `build` context, and its `networks`. The file
must hold one edge for each entry of `depends_on`, from the service to the service that it
waits for. The view must not hold an environment value, a secret or a port of the host.

Reason: The stack has a dozen services on two networks. The view shows what starts before what
and which service can reach which other service.

Test: A unit test builds the view from the compose file and finds each service.
