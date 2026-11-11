---
id: "000689"
title: Internal views show a marked segment as marked
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/src/app/shared/markdown
  - frontend/src/app/features/meetings
  - typst/
---

# Internal views show a marked segment as marked

The internal views must show the marked text with a dashed outline and the tooltip "Wird
öffentlich geschwärzt". The internal PDF must show the marked text as normal text, without a
mark. In the very high contrast view the outline must be solid.

Reason: The keeper must see what the public will not see. The internal PDF is the full record.

Test: A frontend test renders a marker in the internal view and checks the class and the
tooltip.
