---
id: "000745"
title: An observer gets the status mails
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation:
  - backend/app/modules/applications
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# An observer gets the status mails

An added observer must get one mail "Du beobachtest einen Antrag" with the e-mail login link of
the observer address. An observer must get each status mail that the applicant gets. The status
mail of an observer must have a link that ends the observation without a login.

Reason: The observer must learn about a new status without opening the platform, and must be
able to stop the mails alone.

Test: `backend/tests/integration/modules/applications/test_observer_mails.py`: an add sends one
mail, a transition sends the status mail to the applicant and the observer, and the end link
removes the observer.
