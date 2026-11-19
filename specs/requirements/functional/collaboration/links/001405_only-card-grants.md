---
id: "001405"
title: Only a card gives read access to its links
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/todos
scope:
  - backend/app/modules/todos
---

# Only a card gives read access to its links

F/collaboration/todos/000487 must stay as it is for the links of a card. A link between two
elements that are not cards must not give read access. A person who cannot read one end by the
rule of its kind must see that end as "kein Zugriff" (`no access`), without title, URL or
detail.

Reason: A card is a work item with a known set of readers, chosen on purpose. An Antrag or an
invoice has readers by its own rules. If a link between them gave access, a link would become a
way to share an element past its read rule.

Test: A backend unit test links an Antrag to an invoice and reads the invoice links as a person
without a budget read right: the Antrag shows, the invoice gives no access through the link.
