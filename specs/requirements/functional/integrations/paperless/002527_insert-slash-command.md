---
id: "002527"
title: The command Paperless opens the Paperless search in a protocol text
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.slash-menu.spec.ts:MarkdownEditorSlashMenu"
  - "frontend/src/app/features/meetings/top-sheet/top-sheet.component.spec.ts:TopSheetComponent"
implementation:
  - frontend/vendor/ui-kit/markdown-editor/src/slash-menu.ts
  - frontend/src/app/features/meetings/top-sheet/top-sheet.component.ts
  - frontend/src/app/core/api/paperless.service.ts
  - backend/app/modules/paperless_filing/router.py
scope:
  - frontend/src/app/
  - backend/app/
---

# The command Paperless opens the Paperless search in a protocol text

In each Markdown text of a protocol (000862), the command menu of the editor (ui-kit:002769) must
have the command `Paperless` as its last command for a person with `paperless.use` while the
switch `Aus Paperless einfügen` is on. The command must open the Paperless search (002534), and
the picked document goes to the place of the cursor. The format bar of the text and the format
tools of the dock of the Sitzung must have the tool `Paperless` after `Anmerkung`, in the same
group, and the tool must do the same as the command, also in the Markdown source. Without the
permission or with the integration off, the menu must not have the command and the bars must
not have the tool. The text `::` is plain text.

Reason: A person inserts a document of the archive at the place where the Sitzung treats it,
without a download and an upload. One menu holds all inserts, so a person learns one key.

Test: A component test of the protocol text runs the command with and without the permission.
