---
id: "000871"
title: The protocol PDF shows the time above each TOP
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/protocol/test_public_service_unit.py:test_assemble_puts_the_time_of_a_reached_top_above_its_heading"
  - "typst/tests/test_integration.py:test_time_notes_print_centered_above_the_top"
  - "typst/tests/test_markdown.py:test_time_note_without_text_and_a_bad_time"
implementation:
  - backend/app/modules/protocol/markdown.py
  - backend/app/modules/protocol/service.py
  - typst/template/protocol.typ
scope:
  - backend/app/modules/protocol
  - typst/
---

# The protocol PDF shows the time above each TOP

The protocol PDF must show the time of a TOP (000870) as `HH:MM Uhr` in the time zone
Europe/Berlin. The time must be grey, small and centered on its own line above the heading of
the TOP. A TOP without a time must have no line.

Reason: A reader sees the course of the Sitzung, and the time does not compete with the
heading.

Test: Integration test of the typst service: the time line comes before the TOP heading, and a
TOP without a time has none.
