---
id: "001964"
title: No uppercase captions or subheadings
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/styles/base.scss
  - frontend/vendor/ui-kit/src/lib/no-uppercase.spec.ts
  - frontend/src/app/no-uppercase.styles.spec.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit/src/
---

# No uppercase captions or subheadings

No text of the app or the kit is set in capitals by style. A stylesheet must not use
`text-transform: uppercase`, and a caption has no letter spacing for capitals.

- A caption, a column head of a table, a group label of a select or a menu is small semibold
  text (12.5px) in sentence case: the `.cap` class of the kit.
- A heading above a group (an `h2` to `h4` or a `legend` with `.cap`) has the look of the title
  of `app-section`: accent colour, 13.5px, semibold. So a caption heading and a section heading
  are one style, and a new subheading uses `app-section` or `.cap`, never its own CSS.

A code that is uppercase by its nature (a language code such as DE, a file type such as PDF,
a join code) stays as it is, because the text itself is uppercase, not the style.

Reason: letter-spaced uppercase subheadings looked generated and differed from the section
headings of the rest of the app (Frederik, 2026-11-20).

Test: `frontend/src/app/no-uppercase.styles.spec.ts` and `no-uppercase.spec.ts` of the kit fail
on an uppercase rule in a stylesheet. Screenshot review of a dialog with caption headings, a
table and a select with groups, light, dark and very high contrast.
