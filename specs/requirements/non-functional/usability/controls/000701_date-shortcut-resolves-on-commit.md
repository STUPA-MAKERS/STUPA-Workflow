---
id: "000701"
title: A date shortcut becomes the date when the field commits
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/vendor/ui-kit/src/lib/datepicker
  - frontend/src/app/
---

# A date shortcut becomes the date when the field commits

The date field must resolve a shortcut (000700) when the field loses the focus and when the
person presses Enter. The field must then show the resolved date in the date format of the
language and must give the ISO date as its value. The value must never be the shortcut text.
Text that is neither a date nor a shortcut must show the last valid value again, as for a
wrong date. The field must not show a helper text about the shortcuts (000206).

Reason: The form, the API and the other views know only dates. A person must see at once
which date the shortcut gave. Enter must resolve the shortcut, because a form that is sent
with Enter does not blur the field first.

Test: A unit test types `+1w` and blurs, then types `-1d` and presses Enter, and expects the
shown date and the ISO value each time. A test types `+1x` and expects the last value.
