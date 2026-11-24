---
id: "002003"
title: The Markdown editor and the DE texts load in chunks of their own
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/bundle.contract.spec.ts:bundleContract"
implementation:
  - frontend/vendor/ui-kit/views/protocol/src/raw-format.ts
  - frontend/src/app/core/i18n/translations.ts
  - frontend/src/app/core/i18n/translations.de.ts
  - frontend/src/main.ts
  - frontend/angular.json
scope:
  - frontend/src/app
  - frontend/angular.json
---

# The Markdown editor and the DE texts load in chunks of their own

The meeting page must load the Markdown editor (tiptap, KaTeX) only when the TOP sheet shows
it. Only a component that defers the editor may import a value of the editor entry. The DE
texts must be a lazy chunk that the app starts to load before it boots and that the first
paint waits for. The production build must fail when the meeting chunk is larger than 700 kB
or the start bundle is larger than 1 MB.

Reason: A value import of a helper from the editor entry pulled the whole editor into the
meeting chunk (1.39 MB), which every member loaded to follow a meeting. The DE texts were a
quarter of the start bundle and changed its hash with every release, so the browser loaded
them again after each update.

Test: A contract test reads the sources. It fails for a value import of the editor entry
outside the TOP sheet, for a value import of `de.json` in `translations.ts`, and for missing
budgets in `angular.json`.
