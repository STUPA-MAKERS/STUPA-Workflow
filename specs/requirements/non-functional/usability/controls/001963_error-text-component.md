---
id: "001963"
title: An error text in a dialog or a form comes from the kit
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/lib/error-text
  - frontend/src/app/error-text.templates.spec.ts
scope:
  - frontend/src/app/
---

# An error text in a dialog or a form comes from the kit

An error text in a dialog, a sheet or a form (a refusal of the server, a conflict, a rule that
the input breaks) must be an `app-error-text` of the kit. An app template must not write it as
a paragraph with its own error class (`<p class="x__error" role="alert">`).

`app-error-text` is small text in the danger colour, and a screen reader announces it when it
appears (`role="alert"`). With `inset` it indents like the text inside a field (16px), for an
error under a field or a field group. An icon as its first child stands on the line of the
text.

Not covered: the error of one field, which is the `error` input of that field; a box with a
background that stays on the page, which is `app-note kind="error"`.

Reason: 26 error paragraphs in 18 templates each had their own class with the same four lines
of CSS, and three of them had drifted to another size or indent. One component keeps the size,
the colour and the announcement the same everywhere.

Test: `frontend/src/app/error-text.templates.spec.ts` fails on a paragraph with an error class
and `role="alert"` in a template. `error-text.component.spec.ts` of the kit checks the role, the
indent and the rule.
