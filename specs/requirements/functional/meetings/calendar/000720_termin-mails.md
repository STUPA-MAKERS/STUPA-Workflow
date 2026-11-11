---
id: "000720"
title: An invited person gets a mail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - backend/app/modules/calendar/mails.py
  - backend/app/modules/notifications/kinds.py
scope:
  - backend/app/modules/calendar
  - backend/app/modules/notifications
---

# An invited person gets a mail

An invited person must get a mail when the invitation is made, when the start, the end or the
place changes, and when the Termin is deleted. The mail must attach the Termin as an `.ics` file.
The mails must be one notification kind that a person can switch off. The creator must not get a
mail about the own change.

Reason: An invitation that shows only in the Kalender is found too late.

Test: A backend unit test invites a Gremium and counts one mail for each member, and none for a
member who switched the kind off.
