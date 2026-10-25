# typst render service

The service renders a meeting protocol to PDF. It takes the protocol Markdown
that the backend builds (with a YAML frontmatter) and gives back a PDF in the
HSRT design. The layout matches the pytex (LaTeX) HSRT report, which is the
reference for every measurement in the template.

> **Internal only.** The service has no host port. In compose it sits on
> `typst_net`, which has no egress. Do not publish port 8099.

## How it works

1. `typst_service/frontmatter.py` splits off the frontmatter.
2. `typst_service/markdown.py` parses the Markdown (CommonMark + GFM) into a
   JSON tree.
3. `typst_service/document.py` adds the title page, the logos and the
   signatures.
4. `typst_service/compiler.py` writes the tree to a new job directory and runs
   `typst compile` on `template/main.typ` in that directory.

The template reads the tree with `json()`. Text from the Markdown is data. It
never becomes Typst code, so a `#` call or a `$` formula in a protocol cannot
run.

## Endpoint

`POST /render` — send the Markdown as the raw request body.

| Query parameter | Values | Default |
|---|---|---|
| `variant` | `protocol-stupa`, `protocol-asta`, `protocol` | the logos come from the `gremium` key |

To send uploaded logos, use `multipart/form-data` with these fields:

| Field | Content |
|---|---|
| `source` | the Markdown |
| `config` | a JSON object, for example `{"logos": ["a1-logo.png", "INF"]}` |
| `assets` | one file part per logo; the file name is the asset name |

A logo entry is a vendored name (`HSRT`, `INF`, `ASTA`, `STUPA`, `ECHO`,
`MAKERS`, `MAKERS-RAlign`, `MAKERS-Icon`, `Skyline`) or the name of an
uploaded asset (PNG, JPEG, GIF, WebP, SVG or PDF).

An uploaded image of the text travels the same way, as the asset
`img-<uuid>.<ext>` (`png`, `jpg`, `gif`, `webp`). The Markdown refers to it as
`![alt](/api/media/images/<uuid>)`. Only that path with an uploaded asset shows
an image; every other image prints its alt text, because the render has no
network and reads no file of the author. A paragraph that holds only an image
prints it as a block: centered, at most the text width and 12 cm high.

| Status | Meaning |
|---|---|
| 200 | `application/pdf` |
| 400 | bad input: empty source, bad YAML or config, unknown variant or logo, a formula that does not compile |
| 413 | a size or count cap, or the compile time limit |
| 500 | an internal error (no detail) |

`GET /health` — returns `{"status": "ok"}`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `TYPST_MAX_BODY_BYTES` | 33554432 | maximum request size |
| `TYPST_MAX_ASSETS` | 64 | maximum number of assets (logos plus the images of the text) |
| `TYPST_MAX_ASSET_BYTES` | 8388608 | maximum size of one asset |
| `TYPST_COMPILE_TIMEOUT_S` | 60 | wall-clock limit of one compile |
| `TYPST_MAX_CONCURRENCY` | 2 | compiles that run at the same time |

## Development

The design comes from the git submodule `vendor/hsrtreport-typst`. Check it
out first:

```bash
git submodule update --init --recursive
nix develop .#typst          # typst, poppler, Python toolchain
cd typst
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest             # the integration tests need typst and pdftotext
```

The integration tests compare anchor positions with the pytex reference output. If you
change the layout, keep these positions or update the test with a reason.

## Licenses of the vendored files

- `vendor/hsrtreport-typst` — CC BY-SA 4.0 and MIT-0 (see the submodule).
- `fonts/fontawesome/FontAwesome.otf` — SIL OFL 1.1 (`fonts/fontawesome/OFL.txt`).
- `fonts/lmodern/lmmono10-regular.otf` — GUST Font License.
- `packages/preview/mitex/0.2.7` — Apache-2.0.
