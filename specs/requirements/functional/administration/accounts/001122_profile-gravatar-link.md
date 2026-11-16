---
id: "001122"
title: The profile picture links to Gravatar
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/pages/account/profile.component.spec.ts:AccountProfileComponent"
implementation:
  - frontend/src/app/pages/account/profile.component.ts
  - frontend/src/app/pages/account/profile.component.html
  - frontend/src/app/pages/account/profile.component.scss
scope:
  - frontend/src/app/pages/account
---

# The profile picture links to Gravatar

The profile picture on the profile page (`F/administration/accounts/001120`) must link to
`https://gravatar.com/profile` and must open it in a new tab. On a device with a pointer, the
link symbol must cover the picture on hover and on keyboard focus. On a touch device, the link
symbol must always show as a small badge on the corner of the picture. When an admin switched
Gravatar off (`F/administration/accounts/000334`), the picture must have no link and no
symbol.

The link is a navigation of the person, not a request of the app, so the rule that the browser
never calls Gravatar for an image still holds.

Reason: The image comes from Gravatar, so the person changes it there. A touch device has no
hover, so the symbol would never show there. Without Gravatar images a change there has no
effect in the app.

Test: The frontend test finds the link with the target and the symbol, and no link when
Gravatar is off.
