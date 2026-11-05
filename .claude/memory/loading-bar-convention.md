---
name: loading-bar-convention
description: The global loading bar counts GETs only. Background reads opt out with skipLoading() or quietly(); mutations never count
metadata:
  node_type: memory
  type: project
---

The rules are specs in `specs/` of the STUPA-Workflow repository. Read the spec, not this
file:

- `NF/performance/loading/000189` The load bar shows only for slow foreground reads
