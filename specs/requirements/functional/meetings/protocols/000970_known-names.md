---
id: "000970"
title: The known names are the persons of the platform
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation: null
scope:
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# The known names are the persons of the platform

The known names of a Sitzung must be:

1. the name of each person with an account on the platform,
2. the name of the applicant of each Antrag on the agenda,
3. the name of each guest of the Sitzung.

Of each name, the first word is the first name and the last word is the last name. A name of
one word is not a known name. The route `GET /api/meetings/{id}/known-names` must give the list
only to a person who can write a protocol text of the Sitzung, else 403 or 404 as problem+json.
The answer must hold only the pairs of first and last name, without an id or an e-mail address.
An anonymized applicant has no name and gives no pair.

Reason: The more names the editor knows, the fewer names reach the public protocol. Only a
keeper needs the list, and only to mark names.

Test: A backend test reads the list as a keeper and as a member who cannot write, and checks
an account name, an applicant name and a guest name.
