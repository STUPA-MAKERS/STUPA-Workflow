---
name: typst
description: Internal-only protocol Markdown→PDF render service (`typst/`) — FastAPI + the typst CLI, the HSRT design from the hsrtreport-typst submodule, a Markdown→JSON converter and a data-driven Typst template that reproduces the former pytex layout. Single POST /render route, variants protocol-stupa/protocol-asta/protocol, uploaded logos over multipart. Use when working on protocol PDF rendering, the /render contract, the template/layout, fonts/logos, the Dockerfile, or the backend TypstClient in typst/ and backend/app/modules/pdf.
---

# typst render service — `typst`

**Does:** Turns the server-generated protocol Markdown (with YAML frontmatter) into a PDF. The Python side parses the Markdown into a JSON tree. The Typst template (`template/protocol.typ`) reads that tree with `json()` and builds the pages. Text from the Markdown is DATA: it never becomes Typst code, so injection is impossible by construction. The layout reproduces the pytex 1.2.0 protocol variant (KOMA `scrbook` 11pt, HSRTReport).

**Key files:**
- `typst_service/app.py` — FastAPI app: `POST /render`, `GET /health`, raw-body and multipart parsing, body/asset caps, error→status map, path scrubbing, compile semaphore.
- `typst_service/frontmatter.py` — YAML frontmatter split with `yaml.BaseLoader` (every scalar stays a string: `18:30` is NOT sexagesimal). `parse_frontmatter` also returns the records: a list of flat mappings (string values only), today `keepers`. `split_frontmatter` leaves them out.
- `typst_service/markdown.py` — marko (CommonMark + GFM) → JSON nodes. Callouts (`[!NOTE]`… and protocol `[!beschluss]`/`[!abstimmung]`/`[!aufgabe]`/`[!frist]`/`[!unterschriften]`), tally parsing, `{{shortcodes}}`, `$…$`/`$$…$$` math, ASCII arrows → math symbols, drops the editor's `:::antrag{#id}` fences. `MAX_DEPTH` caps nesting.
- `typst_service/document.py` — title, title-page data rows (incl. `datalines`), default logos per variant, `logos`/`footer_logos` config, signatures. The keepers (Z3): the `Protokoll` row lists every period (`Name (TOP 1 – TOP 3)`, or the times without a TOP number; one keeper prints the name only), the `Schriftführung` role gets one signature line per keeper, and a later period adds the line "Die Protokollführung übernimmt <Name> um <hh:mm> Uhr." below the heading of its `from_top` agenda item. Without `keepers` the legacy `protokoll` name stays in use. `entschuldigt` (alias `excused`) is its own list row. `started_at` (`YYYY-MM-DD HH:MM`) fills a missing `datum` or `beginn`.
- `typst_service/compiler.py` — one temp dir per job as the Typst `--root` (`main.typ`, `doc.json`, `assets/`, symlinks `tpl`→`template/`, `hsrt`→`vendor/hsrtreport-typst/src`), `--ignore-system-fonts`, offline `--package-path`, wall-clock timeout that kills the process group.
- `template/protocol.typ` — the layout. `template/main.typ` — job entry point.
- `typst_service/selftest.py` — renders a sample per variant during `docker build`.
- `vendor/hsrtreport-typst` — git submodule: DIN/Blender fonts, logos (SVG), Skyline.
- `fonts/` — FontAwesome 4.7 (box icons, OFL) and Latin Modern Mono (code, GUST).
- `packages/preview/mitex/0.2.7` — vendored mitex (LaTeX math → Typst math, offline).
- `Dockerfile` — `python:3.13-slim` + pinned, sha256-checked typst musl binary; uid 10001.

**Frontmatter contract (backend → typst):** `title`, `typ`, `gremium`, `cd`, `datum`, `date`, `beginn`, `ende`, `started_at`, `protokoll` (legacy single name), `keepers` (list of records `name`, `from`, `to`, `from_top`, `to_top`; all strings, empty keys left out), `anwesend`, `entschuldigt`, `abwesend`, `beschlussfaehigkeit`, `datalines`, `unterschriften`. The public variant sends no names and no `keepers`. Deploy the api and the typst images together when the contract changes; the legacy `protokoll` key keeps an older typst image working.

**API surface:**
- `POST /render?variant=protocol-stupa|protocol-asta|protocol` — raw body (Markdown) or `multipart/form-data` with `source`, `config` (JSON object), repeated `assets` (file name = asset name, plain image file name only). Returns `application/pdf` + `X-Render-Duration-Seconds`. `variant` omitted/`protocol` ⇒ default logos from the `gremium` key (stupa/asta/echo, else STUPA).
- Errors (`{"error": …}`, paths scrubbed): 400 bad input / unknown variant or logo / bad YAML / compile error (e.g. malformed formula); 413 body/asset caps or compile timeout (permanent, it repeats); 500 anything else without detail.
- `GET /health` → `{"status": "ok"}`.

**Conventions & gotchas:**
- **The layout is calibrated, not guessed.** Every block-to-block gap comes from `gap-after-text` / `gap-after` in `protocol.typ`, measured from pytex output with `pdftotext -bbox` and pixel scans. Blocks carry NO spacing of their own (`set block(above: 0pt, below: 0pt)`, `par.spacing: 0pt`). `tests/test_integration.py` pins anchor positions — a template change that moves them fails CI.
- **Box icons are per-glyph:** LaTeX `\vcenter`ed each FontAwesome glyph, so `icons.<name>.top` holds a measured offset. pytex asked for `vote-yea`, `clipboard-check`, `clock`, which FontAwesome 4 lacks — those places have no icon on purpose (tally box, Aufgabe box, the space before a `{{time}}`).
- **Deliberate fixes over pytex:** public `datalines` reach the title page; `€` in a callout; bold in a vote question; `:::antrag` fences dropped; `~~strike~~`; ISO date → `15.06.2026, 18:30`; the title-page label column widens for a long label.
- **Page breaks can differ from pytex** (TeX's page builder shrinks glue on full pages; Typst never shrinks). Boxes are unbreakable, like the LaTeX minipage.
- **Typst version:** pinned in `Dockerfile` and the CI `typst` job (keep both in step). The flake dev shell may ship another version; the layout tests pass on 0.14 and 0.15.
- **Egress-less:** compose puts `typst` on `typst_net` only (`internal: true`), read-only rootfs, tmpfs `/tmp`, `cap_drop: ALL`.
- **Env:** `TYPST_MAX_BODY_BYTES` (32 MiB), `TYPST_MAX_ASSETS` (16), `TYPST_MAX_ASSET_BYTES` (2 MiB), `TYPST_COMPILE_TIMEOUT_S` (60), `TYPST_MAX_CONCURRENCY` (2), plus `TYPST_BIN`/`TYPST_FONT_DIRS`/`TYPST_TEMPLATE_DIR`/`TYPST_HSRT_DIR`/`TYPST_PACKAGE_DIR` for the layout.
- **Tests:** `nix develop .#typst -c sh -c 'cd typst && .venv/bin/pytest'`. Unit tests fake the compiler; integration tests need `typst` + `pdftotext` on PATH and skip otherwise.

**Related:** be-pdf, be-protocol, deploy
