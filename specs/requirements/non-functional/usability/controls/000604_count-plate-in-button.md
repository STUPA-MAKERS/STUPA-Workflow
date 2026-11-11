---
id: "000604"
title: A count in a button is the count plate of the kit button
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/vendor/ui-kit/src/lib/button
  - frontend/src/app/pages/applications/applications-detail.component.html
  - frontend/src/app/features/apply/status-timeline.component.html
  - frontend/src/app/features/todos/card-detail/todo-card-detail.component.html
scope:
  - frontend/vendor/ui-kit/src/lib/button
  - frontend/src/app
---

# A count in a button is the count plate of the kit button

A count at the end of a button ("Kommentare 3") must come from the `count` input of the kit
button. A page must not draw its own count plate inside a button.

Reason: Three pages drew the same plate inside the label, and each plate sat on the top of
the line box, about 1px below the text.

Test: The unit spec of the kit button checks the plate. A search for a count plate class in
the app pages finds none.
