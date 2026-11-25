---
id: "003024"
title: An Event has a link to its shop
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/rules.py
  - frontend/src/app/pages/events/event-detail.component.html
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# An Event has a link to its shop

An Event can have the field `Shop` (`shopUrl`): the address where people buy tickets or goods
for the Event. The address must be an http or https address, else the API must answer 422
`event_url_invalid`. The detail of the Event must show the shop as a link that opens in a new
tab.

Reason: The tickets of a party or the goods of a sale are sold in an external shop. The people
who work on the Event need the address at one place.

Test: A backend unit test refuses `javascript:alert(1)` and accepts `https://shop.example/x`. A
frontend unit test finds the link with `target="_blank"` in the detail.
