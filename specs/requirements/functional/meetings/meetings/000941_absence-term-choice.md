---
id: "000941"
title: The absence count and the export offer each term
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/gremien_overview/service.py
  - frontend/src/app/features/gremien
scope:
  - backend/app/modules/gremien_overview
  - backend/app/modules/meetings
  - frontend/src/app/features/gremien
---

# The absence count and the export offer each term

The count of the unexcused absences of a Gremium (000920) and the attendance export must offer
each term in which the Gremium had a meeting. The current term must be the choice at the
start.

Reason: A question about the absences of a member often comes after the end of the Amtszeit.

Test: A backend unit test reads the count of a past term and finds the absences of this term
only.
