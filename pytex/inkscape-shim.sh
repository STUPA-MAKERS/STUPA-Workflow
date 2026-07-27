#!/bin/sh
# Minimal `inkscape` CLI shim backed by rsvg-convert (T-21, the image stays slim).
#
# The IncludeImage step of pytex converts SVG logos with exactly this shell-out:
#   inkscape <src.svg> --export-type=pdf --export-filename=<dst.pdf>
# Without the shim the CD variants with SVG logos (protocol-asta: ASTA.svg) lose
# their assets and tectonic stops with "Unable to load picture or PDF file".
# Real Inkscape would add hundreds of MB to the image. rsvg-convert (librsvg)
# renders the flat vector logos the same way. The shim fails loudly on any other
# call. It never guesses.
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
