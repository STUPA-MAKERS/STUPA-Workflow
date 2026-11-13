---
id: "000863"
title: An embedded PDF shows as a file badge
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
implementation: null
scope:
  - frontend/src/app/shared/markdown
  - frontend/src/app/features/meetings
  - frontend/src/app/features/public-protocols
  - frontend/vendor/ui-kit/markdown-editor
---

# An embedded PDF shows as a file badge

The app must show the reference of an embedded PDF (000862) as a file badge with a PDF icon,
the file name and the page count. This applies in the editor, in the read view of a Sitzung
and on the public protocol page. A click or Enter on the badge must open the PDF in the overlay
file viewer of the kit. The viewer must have a download button.

Reason: A PDF is too large to show in the text. The badge keeps the text readable, and the
overlay opens the document without a page change.

Test: Component tests of the Markdown view and of the editor: the badge renders, and a click
opens the viewer with the PDF.
