---
id: "000942"
title: A changed period does not reach a started case
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/livevote/test_meeting_periods_unit.py:test_excuse_late_reads_the_period_of_the_meeting_not_the_setting"
  - "backend/tests/unit/modules/livevote/test_meeting_periods_unit.py:test_a_period_of_0_days_is_refused"
  - "backend/tests/integration/modules/livevote/test_meeting_periods.py:test_periods_start_values_update_bounds_and_audit"
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

A meeting must keep the value of `lateExcuseDays` (000917) of the time it was made. A later
change of this setting must apply only to a meeting that is made after the change. The values
`inviteDaysOrdinary`, `inviteDaysExtraordinary`, `lateExcuseDays` and `circularMinDays` must
each be 1 day or more.

A meeting does not keep the two invitation periods, because they give only a warning in the
meeting form. A circular vote does not keep `circularMinDays`, because the platform checks this
value only at the open of the vote.

Reason: A period that changes after the start makes a running case valid or not valid after
the fact. Only the window of the late excuse is read again after the start. A period of 0 days
is no period.

Test: A backend unit test changes `lateExcuseDays` after a meeting was made and reads the
window of this meeting, and a test of the settings route sends 0 and gets a 422.
