---
id: "000942"
title: A changed period does not reach a started case
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/meetings/periods.py
  - backend/app/modules/meetings/models.py
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - backend/app/modules/voting
  - backend/app/modules/admin
---

# A changed period does not reach a started case

A meeting must keep the values of `inviteDaysOrdinary`, `inviteDaysExtraordinary` and
`lateExcuseDays` (000917) of the time it was made. A circular vote must keep the value of
`circularMinDays` of the time it opened. A later change of the settings must apply only to a
meeting or a circular vote that starts after the change. Each of these periods must be 1 day
or more.

Reason: A period that changes after the start makes a running case valid or not valid after
the fact. A period of 0 days is no period.

Test: A backend unit test changes `lateExcuseDays` after a meeting was made and reads the
window of this meeting, and a test of the settings route sends 0 and gets a 422.
