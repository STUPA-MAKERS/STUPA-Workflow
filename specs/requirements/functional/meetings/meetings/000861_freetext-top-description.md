---
id: "000861"
title: A free-text TOP takes a description that opens its text as a quote
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/livevote/test_agenda_freetext_description_unit.py:test_a_description_starts_the_text_as_a_quote"
  - "backend/tests/unit/modules/livevote/test_agenda_freetext_description_unit.py:test_block_quote_prefixes_every_line"
  - "frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.spec.ts:freetextDescription"
  - "mcp/antragsplattform_mcp/tests/test_agenda_tools.py:test_add_agenda_item_sends_the_description"
implementation:
  - backend/app/modules/livevote/schemas.py
  - backend/app/modules/meetings/agenda_service.py
  - frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.ts
  - mcp/antragsplattform_mcp/tools/meetings.py
scope:
  - backend/app/modules/livevote
  - backend/app/modules/meetings
  - frontend/src/app/features/meetings
  - mcp
---

# A free-text TOP takes a description that opens its text as a quote

The dialog "TOP hinzufügen" must show an optional multi-line field "Beschreibung" for the kind
Freitext. When the person adds the TOP with a description, the TOP text must start with the
description as a Markdown block quote: each line gets the prefix `> `. Thus the description goes
into the protocol as a block quote. A free-text TOP without a description must have an empty text,
as before. The kinds Antrag and To-Do must not show the field.
