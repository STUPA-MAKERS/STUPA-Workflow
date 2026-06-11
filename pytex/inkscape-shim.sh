#!/bin/sh
# Minimal `inkscape` CLI shim backed by rsvg-convert (T-21, image stays slim).
#
# pytex's IncludeImage converts SVG logos by shelling out exactly:
#   inkscape <src.svg> --export-type=pdf --export-filename=<dst.pdf>
# Without it the CD variants with SVG logos (protocol-asta: ASTA.svg) lose
# their assets and tectonic aborts with "Unable to load picture or PDF file".
# Real Inkscape would add hundreds of MB to the image; rsvg-convert (librsvg)
# renders the flat vector logos identically. Any unexpected invocation fails
# loudly instead of guessing.
set -eu

src=""
type=""
out=""
for arg in "$@"; do
  case "$arg" in
    --export-type=*) type="${arg#--export-type=}" ;;
    --export-filename=*) out="${arg#--export-filename=}" ;;
    -*) echo "inkscape-shim: unsupported option: $arg" >&2; exit 64 ;;
    *) src="$arg" ;;
  esac
done

[ "$type" = "pdf" ] || { echo "inkscape-shim: only --export-type=pdf supported" >&2; exit 64; }
[ -n "$src" ] || { echo "inkscape-shim: missing source file" >&2; exit 64; }
[ -n "$out" ] || { echo "inkscape-shim: missing --export-filename" >&2; exit 64; }

exec rsvg-convert --format=pdf --output="$out" "$src"
