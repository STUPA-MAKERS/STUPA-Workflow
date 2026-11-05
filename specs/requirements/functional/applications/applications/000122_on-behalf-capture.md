---
id: "000122"
title: An Antrag can be captured on behalf of a person
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# An Antrag can be captured on behalf of a person

A holder of `application.create_on_behalf` can capture an Antrag for an existing account or
for a guest with name and e-mail. The Antrag belongs to the applicant. The applicant gets the
mail "Für dich wurde ein Antrag erfasst". The detail shows "Erfasst von <Name> am <Datum>" and
an optional "Eingang". The dialog follows the pattern of "Buchung hinzufügen".
