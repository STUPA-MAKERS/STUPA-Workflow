---
id: "001140"
title: A TOP carries an estimated duration
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/livevote/test_agenda_duration_unit.py:test_a_duration_outside_1_to_480_is_refused"
  - "backend/tests/unit/modules/livevote/test_agenda_duration_unit.py:test_a_new_freetext_item_takes_the_duration"
  - "backend/tests/unit/modules/livevote/test_agenda_duration_unit.py:test_set_duration_changes_clears_and_audits_once"
  - "backend/tests/unit/modules/livevote/test_agenda_duration_unit.py:test_set_duration_on_a_closed_meeting_is_refused"
  - "backend/tests/unit/modules/livevote/test_agenda_duration_unit.py:test_the_routes_pass_the_duration"
  - "backend/tests/unit/modules/livevote/test_agenda_duration_unit.py:test_the_duration_route_needs_the_write_right"
  - "frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.spec.ts:topDuration"
  - "frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.spec.ts:durationMenu"
  - "frontend/src/app/features/meetings/agenda-plan.util.spec.ts:minutesField"
  - "mcp/antragsplattform_mcp/tests/test_agenda_tools.py:test_add_agenda_item_sends_the_duration"
  - "mcp/antragsplattform_mcp/tests/test_agenda_tools.py:test_set_agenda_item_duration_puts_the_minutes"
implementation:
  - backend/app/modules/meetings/models.py
  - backend/app/modules/meetings/agenda_service.py
  - backend/app/modules/livevote/router.py
  - backend/app/modules/livevote/schemas.py
  - backend/migrations/versions/9f610130db84_agenda_item_estimated_minutes.py
  - frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.ts
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.ts
  - mcp/antragsplattform_mcp/tools/meetings.py
scope:
  - backend/app/modules/meetings
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
  - mcp
---

# A TOP carries an estimated duration

Each TOP of a Sitzung must take an optional estimated duration in whole minutes, from 1 to 480.
The dialog "TOP hinzufügen" must show the optional number field "Dauer" with the unit `Min.` for
every kind of TOP. The row menu of a TOP must hold the entry "Dauer ändern", which opens a dialog
with the same field. Only a person who may change the agenda must set or clear the duration. An
empty field must clear it. The MCP tools that add or change a TOP must take the duration too.

Reason: Ticket T-0019 asks for an estimate per TOP ("z.B. 10 min"), so that the agenda can
compute a time plan (001141).

Test: Unit test of the agenda service: a value outside 1 to 480 is refused, and an empty value
clears the duration. Component test of the dialog: the field is shown for each kind, and the row menu holds "Dauer ändern".
