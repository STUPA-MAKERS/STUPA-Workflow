---
id: "001083"
title: A file that the viewer shows has a sandboxed inline preview
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/test_inline_preview.py:test_inline_preview_headers"
implementation:
  - backend/app/shared/preview.py
  - deploy/web/nginx.conf
scope:
  - backend/app/modules
  - deploy/web/nginx.conf
---

# A file that the viewer shows has a sandboxed inline preview

Every route that serves a PDF or a raster image for 001080 must accept `?inline=true`. With it,
the route must answer `Content-Disposition: inline`, `X-Frame-Options: SAMEORIGIN` and the CSP
`default-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'; sandbox`.
Without it, the route must answer as before. The route must check the access of the caller in
the same way for both answers. The routes are the Antrag PDF, the Haushaltsplan PDF, the
protocol PDFs, the public protocol PDF, the receipt of an invoice and the logos of a CD variant
and of the branding. An SVG logo must stay a download, because the viewer does not frame it.

Reason: The SPA may frame only its own origin. The `sandbox` directive gives the framed file an
opaque origin, so a PDF polyglot cannot run in the origin of the app (000264).

Test: Unit test per route: with `?inline=true` the answer has the three headers, without it the
answer is `attachment`, and a caller without access gets 404 in both cases.
