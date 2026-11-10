---
id: "000600"
title: Every development thread has a card on the Plattform board
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - .
scope:
  - .
---

# Every development thread has a card on the Plattform board

An agent that does development work in a project thread must keep one card for the thread on
the prod to-do board "Plattform". It must create the card when the work starts, or reuse the
card whose description holds the marker `_Board-Sync · thread=<thread id>_`. It must add each
pull request of the thread to the card description, with its state. It must move the card to
"In Arbeit" while it works, to "Wartet" while the owner must act or a pull request is open,
and to "Erledigt" when the work is finished. It must assign the card to the Bot principal.

Reason: The owner wants to see all development work in one place. A scheduled run in the
evening repairs a card that a thread missed.

Test: The scheduled board sync reports each thread that had no card or a card in the wrong
column.
