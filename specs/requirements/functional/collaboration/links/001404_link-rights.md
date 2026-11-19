---
id: "001404"
title: A person links what the person reads and writes on one end
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/links/access.py
scope:
  - backend/app/modules/links
---

# A person links what the person reads and writes on one end

A person must be able to add or remove a link only when the person reads both elements and may
change at least one of them. The change right of each kind must be:

| Kind | Change right |
| --- | --- |
| Antrag | the edit right of the Antrag |
| meeting, TOP | `session.manage` in the Gremium of the meeting |
| vote | `vote.manage` in the Gremium of the vote |
| Termin | the creator, or `calendar.manage` |
| Gremium | `admin.gremien` |
| invoice, Buchung | `budget.book` on the cost centre |
| cost centre | `budget.structure` on the cost centre |
| ticket | `ticket.manage` |
| card | `todo.write` on the board of the card |

Reason: A link changes how others see an element, so it needs a change right. One end is
enough, so that the person who works on an invoice can link it to an Antrag that the person
only reads.

Test: A backend unit test per kind refuses a person with read rights only on both ends and
accepts a person with the change right on one end.
