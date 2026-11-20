---
id: "001890"
title: A form in place of a detail has the head bar of "Antrag bearbeiten"
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/shared/ui/pane-form/pane-form.component.spec.ts:PaneFormHeadComponent"
  - "frontend/src/app/shared/ui/pane-form/pane-form.component.spec.ts:FormBar"
implementation:
  - frontend/src/app/shared/ui/_form-bar.scss
  - frontend/src/app/shared/ui/pane-form
  - frontend/src/app/pages/applications/applications-detail.component.scss
scope:
  - frontend/src/app/
---

# A form in place of a detail has the head bar of "Antrag bearbeiten"

A form that takes the place of a detail must have the same head as "Antrag bearbeiten": one bar
of 60px on the surface one step up, with a line below it. At the start the bar shows an icon and
the title in bold body text. At the end it shows the text button "Abbrechen". A subtitle follows
the title on the same line, muted, after a middle dot. The head has no large title and no round
close button.

This applies to "Antrag bearbeiten", "Antrag erfassen", "Buchung anlegen" and "Buchung
bearbeiten", "Umschichtung buchen" and "Umschichtung bearbeiten", and "Rechnung anlegen",
"Rechnung prüfen" and "Rechnung bearbeiten".

The icon of a form for a new thing is the icon of that thing: Buchung `swap`, Umschichtung
`repeat`, Rechnung `receipt`, Antrag `fileplus`. The icon of an edit is the pen.

In the one-view layout the form docks in the bar of the layout, as before. The phone sheet keeps
its own head.

Reason: The forms for a new thing had a large title and a round close button, the edit of an
Antrag had a compact bar. The same kind of surface looked different.

Test: The unit tests of the head render the icon, the title, the subtitle and "Abbrechen", and
read the styles of the head and of the Antrag edit for the one shared bar.
