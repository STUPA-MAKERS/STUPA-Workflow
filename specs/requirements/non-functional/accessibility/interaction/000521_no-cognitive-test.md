---
id: "000521"
title: The login and the captcha need no cognitive test
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/antiabuse
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - backend/app/modules/antiabuse
---

# The login and the captcha need no cognitive test

The login and the public forms must not ask for a puzzle, a picture choice or a text from an
image. The captcha must work without a user action.

Reason: WCAG 3.3.8. ALTCHA uses a proof of work, so it obeys this rule.
