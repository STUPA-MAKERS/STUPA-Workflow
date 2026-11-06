---
id: "000049"
title: A visual bug is checked on pixels
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - frontend/
---

# A visual bug is checked on pixels

A visual bug must be examined on a screenshot of the painted pixels. It must not be decided
from geometry or computed styles alone.

Reason: Geometry can be correct while a layer paints over the content.
