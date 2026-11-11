---
id: "000666"
title: A create form has the name of its button
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/core/i18n/catalog/de.json
  - frontend/src/app/core/i18n/catalog/en.json
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A create form has the name of its button

The button that creates an item must have the text "… anlegen". The form or dialog that it
opens must have the same text as its title. "Neue Umfrage" must become "Umfrage anlegen",
"Buchung hinzufügen" must become "Buchung anlegen" and "Rechnung hinzufügen" must become
"Rechnung anlegen". "… hinzufügen" must be used only where an item is added to another item,
for example "Unterbuchung hinzufügen".

"Antrag erfassen" and "Antrag stellen" keep their texts, because they name two different
ways to create an Antrag.

Reason: The button "Buchung anlegen" opens a form with the title "Buchung hinzufügen". The
person reads two names for one action.

Test: A unit test compares the catalog text of each floating create button with the title of
its form.
