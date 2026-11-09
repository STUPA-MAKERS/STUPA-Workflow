---
id: "000579"
title: An unreachable server shows no error toast, and the page loads again
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/src/app/core/
scope:
  - frontend/src/app/
---

# An unreachable server shows no error toast, and the page loads again

A load that fails because the server is unreachable (000578) or the browser is offline must
not show the error toast of 000576. When the offline bar goes, the page must load its
content again without an action of the person.

Reason: The offline bar already tells the cause, and a second message for the same cause is
noise. After a deploy, the page must recover by itself.

Test: A unit test makes a list load fail with 503, expects no error toast, ends the
unreachable state and expects a second load request.
