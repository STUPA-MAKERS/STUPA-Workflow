---
name: be-media
description: Markdown images — upload, clean and serve the images of the Markdown texts (protocol TOPs, to-do cards, chat messages). One canonical reference `![alt](/api/media/images/<uuid>)`; Pillow re-encode (EXIF/GPS stripped, ≤ 2400 px, same format), no ClamAV pass; table markdown_image (no uploader column); routes POST/GET /api/media/images and the public GET /api/public/protocols/{id}/images/{image_id}; the protocol render sends the images to typst as `img-<uuid>.<ext>` assets within a budget. Use when working on image upload, the canonical image path, image headers, MarkdownImage, MediaService, render_assets, or images in the protocol PDF in backend/app/modules/media.
---

# Media — `backend/app/modules/media`

**Does:** Takes an image file from a principal, decodes it with Pillow, strips every
metadata block, scales it down and encodes it again in its own format. It stores the
result in the attachment bucket and answers the canonical Markdown path. It streams the
image to any session, and the image of a public protocol without login. It collects the
images of a protocol for the typst render.

**Key files:**
- `refs.py` — the canonical reference. `IMAGE_PATH_RE`
  (`^/api/media/images/<lowercase uuid>$`), `image_path`, `is_image_path`,
  `image_ids_in(*texts)` (ids of `](/api/media/images/<uuid>)` destinations, first
  appearance order, no duplicates; a title and the `<…>` form count).
- `images.py` — `clean_image(data) -> CleanImage` (`data, mime, width, height`),
  `ImageRejected`. libmagic sniff (`files.mime.sniff_mime`) must be PNG, JPEG, GIF or
  WEBP; `Image.open(..., formats=[<sniffed>])`; guards `MAX_PIXELS` (40 MP per frame),
  `MAX_FRAMES` (300), `MAX_TOTAL_PIXELS` (200 MP), Pillow's own bomb warning raised as
  an error. `ImageOps.exif_transpose`, `MAX_SIDE` 2400 px (LANCZOS; a palette image
  goes through RGBA), `info` cleared except `transparency`, ICC kept up to 256 KiB.
  JPEG/WEBP quality 85. An animated GIF or WEBP keeps its frames (RGBA, durations,
  loop); an APNG keeps its first frame.
- `models.py` — `MarkdownImage` (`markdown_image`: `id` uuid4 set in Python,
  `storage_key`, `mime`, `size`, `width`, `height`, `created_at`; CHECKs
  `ck_markdown_image_mime|size|dimensions`). `IMAGE_KEY_PREFIX` `media/images/`,
  `image_storage_key`, `IMAGE_MIMES`. Migration `066ff25554e2` (idempotent).
- `service.py` — `MediaService(session, storage, max_bytes)`: `upload` (clean in a
  thread, 413 when the result passes `max_bytes`, add + flush, `put`, commit), `open`
  (404 unknown, 503 storage), `render_assets(markdown)` with `RENDER_MAX_IMAGES` 48,
  `RENDER_MAX_BYTES` 24 MiB, `RENDER_MAX_ASSET_BYTES` 8 MiB; `render_asset_name`
  (`img-<uuid>.png|jpg|gif|webp`).
- `router.py` — `router` (`/media/images`) and `public_router` (`/public/...`),
  `IMAGE_CSP`, `get_media_service`, `get_public_protocols`.

**API surface:**
- `POST /api/media/images` — multipart `file`. Principal only (applicant and anonymous:
  401). `enforce_media_body_cap` (`markdown_image_max_bytes` + 64 KiB),
  `rate_limit_media_images` (`rl_media_images_per_hour` 120 per `sub`, MCP exempt),
  capped read. 201 `{id, url, mime, width, height, size}`. 413 / 415 (SVG, PDF, text,
  undecodable, bomb) / 429 / 503 (storage off or `put` failed).
- `GET /api/media/images/{id}` — any session: principal or magic-link applicant, else
  401. 404 unknown id. Streams from storage. Headers: stored `Content-Type`,
  `Content-Disposition: inline`, `X-Content-Type-Options: nosniff`,
  `Content-Security-Policy: default-src 'none'; sandbox`,
  `Cache-Control: private, max-age=31536000, immutable`.
- `GET /api/public/protocols/{protocol_id}/images/{image_id}` — no login,
  `rate_limit_public_protocol_images` (`rl_public_protocol_images_ip_per_hour` 3000).
  404 unless the protocol is visible (`PublicProtocolService._visible`) AND
  `public_image_ids` (snapshot `markdown` plus the `markdown` of every public TOP)
  holds the id. Same headers with `Cache-Control: public, max-age=86400`, plus the
  `X-Robots-Tag: noindex` of every `/api/public/` answer.

**Conventions & gotchas:**
- **No ClamAV pass, on purpose.** The stored bytes come from Pillow, never from the
  client, so a polyglot or a payload in a metadata block does not survive. Do not
  store the upload bytes "as is" for any format, and never add SVG.
- **No uploader column.** A principal FK would pull the table into the account merge
  and the erasure. The id is a random uuid4; reading needs a session on top. The
  backup mirrors the image objects with the attachment bucket.
- **The image headers win.** `SecurityHeadersMiddleware` sets its defaults with
  `setdefault`, so the route's CSP replaces the API CSP. The edge nginx maps both image
  paths to an empty `Cache-Control` (`map $ap_cache_control`) and gives
  `POST /api/media/images` the 11m body limit; the general `/api/` limit is 1 MB.
- **Protocol render** (`ProtocolService._render_pdf`): `render_assets` of the final
  Markdown merges with the CD logo assets. An unknown id, a missing object, a too
  large image or one over the budget stays out and the PDF prints the alt text; an
  image never fails a render. `sanitize_user_markdown` keeps the canonical path (it
  neutralizes every other absolute or `..` image path). typst 0.15 reads all four
  formats, WEBP and animations included, so no conversion happens.
- **typst side** (`typst/typst_service/markdown.py`): an `Image` whose dest matches the
  canonical path and whose `img-<uuid>.*` asset came with the request becomes
  `{"t":"image","asset":…,"alt":…}`; a paragraph of only that image becomes
  `{"t":"figure",…}` (centered, ≤ text width, ≤ 12 cm high, never above its natural
  size). Every other image stays the alt-text node.
- Settings: `markdown_image_max_bytes` (10 MiB), `rl_media_images_per_hour`,
  `rl_public_protocol_images_ip_per_hour`.
- Tests: `tests/unit/modules/media/`, `tests/unit/modules/protocol/test_protocol_images.py`,
  fakes in `tests/_support/media_fakes.py` (`MediaSession`, `MediaStorage`, `add_image`).

**Related:** be-files, be-protocol, typst, be-antiabuse, deploy, frontend
