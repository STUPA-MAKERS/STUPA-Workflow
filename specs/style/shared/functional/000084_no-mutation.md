---
id: "000084"
title: A value is not mutated
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/
  - backend/worker/
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - mcp/
  - typst/typst_service/
---

# A value is not mutated

Code must not change a value in place. In Python, it must not use `.append`, `.add`, `.update`,
`x[k] = v` or `del`. In TypeScript, it must not use `.push`, `.splice`, an in-place `.sort()`
or `delete`. It must not use `Object.assign` onto an existing object. Code must build the new
value whole.
