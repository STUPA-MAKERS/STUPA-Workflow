// Meeting protocol in the HSRT design.
//
// The render service converts the protocol Markdown into a JSON tree and
// compiles `main.typ`, which calls `protocol()` with that tree. Every text
// value in the tree is data: this file turns it into content and never
// evaluates it. Only a formula goes through mitex, which converts the LaTeX
// body inside math mode.
//
// The layout reproduces the pytex protocol variant (KOMA-Script `scrbook` at
// 11pt with the HSRTReport page setup), so a protocol looks the same as
// before. The lengths below were measured from pytex output. A gap is the
// distance between the bottom edge of one block and the top edge of the next:
// the text line box for text, the tinted area for a box, the outer rules for
// a table, the frame for a code block.
//
// Job root layout (see `typst_service/compiler.py`):
//   /main.typ        the entry point
//   /doc.json        the document tree
//   /assets/<name>   the uploaded logos
//   /tpl/            this directory
//   /hsrt/           the `src/` directory of hsrtreport-typst

#import "@preview/mitex:0.2.7": mi, mitex

// -- fonts and sizes (KOMA-Script 11pt) -------------------------------------

#let body-font = ("DIN", "New Computer Modern")
#let head-font = ("Blender", "New Computer Modern")
#let mono-font = ("Latin Modern Mono", "DejaVu Sans Mono")
#let icon-font = "FontAwesome"
#let math-font = "New Computer Modern Math"

#let size = (
  footnote: 9pt,
  small: 10pt,
  normal: 10.95pt,
  large: 12pt,
  Large: 14.4pt,
  Huge: 24.88pt,
)
// \baselineskip of \normalsize.
#let baseline = 13.6pt
// The line box of DIN (ascender to descender) is 1.211 em high. The leading
// is the rest of the LaTeX baseline skip.
#let leading = baseline - 1.211 * size.normal

// -- colors (xcolor base colors and the HSRT palette) -----------------------

#let rgbf(r, g, b) = rgb(r * 100%, g * 100%, b * 100%)
#let palette = (
  red: rgbf(1, 0, 0),
  green: rgbf(0, 1, 0),
  blue: rgbf(0, 0, 1),
  orange: rgbf(1, 0.5, 0),
  gray: rgbf(0.5, 0.5, 0.5),
  britishracinggreen: rgbf(0.0, 0.26, 0.15),
  eggplant: rgbf(0.38, 0.25, 0.32),
  hanblue: rgbf(0.27, 0.42, 0.81),
  navyblue: rgbf(0.0, 0.0, 0.5),
  hsrtlink: rgbf(0.161, 0.31, 0.427),
  hsrturl: rgbf(0.071, 0.212, 0.322),
)

// xcolor `color!p`: p percent of the color, the rest white.
#let tint(c, percent) = color.mix((c, percent), (white, 100% - percent), space: rgb)

// -- icons (FontAwesome 4.7) ------------------------------------------------

// Only the glyphs that pytex showed. pytex also asked for `vote-yea`,
// `clipboard-check` and `clock`, which FontAwesome 4 lacks, so those places
// stay without an icon. LaTeX centers each glyph on the math axis
// (`\vcenter`), so every icon has its own offset: `top` is the distance from
// the top edge of the box to the top of the icon line, measured from pytex
// with the offset of its box style included.
#let icons = (
  info-circle: (glyph: "\u{f05a}", top: 3.57pt),
  exclamation-triangle: (glyph: "\u{f071}", top: 5.49pt),
  check-circle: (glyph: "\u{f058}", top: 5.71pt),
  exclamation-circle: (glyph: "\u{f06a}", top: 5.68pt),
  gavel: (glyph: "\u{f0e3}", top: 6.41pt),
  hourglass-half: (glyph: "\u{f252}", top: 5.56pt),
  thumbs-up: (glyph: "\u{f164}", top: 5.63pt),
  thumbs-down: (glyph: "\u{f165}", top: 3.92pt),
)

// -- logos ------------------------------------------------------------------

#let vendored-logos = (
  HSRT: "/hsrt/assets/images/logos/HSRT.svg",
  INF: "/hsrt/assets/images/logos/INF.svg",
  ASTA: "/hsrt/assets/images/logos/ASTA.svg",
  STUPA: "/hsrt/assets/images/logos/STUPA.svg",
  ECHO: "/hsrt/assets/images/logos/ECHO.svg",
  MAKERS: "/hsrt/assets/images/logos/MAKERS.svg",
  MAKERS-RAlign: "/hsrt/assets/images/logos/MAKERS-RAlign.svg",
  MAKERS-Icon: "/hsrt/assets/images/logos/MAKERS-Icon.svg",
  Skyline: "/hsrt/assets/images/Skyline.svg",
)

#let logo(entry, height) = {
  let path = if "asset" in entry { "/assets/" + entry.asset } else { vendored-logos.at(entry.name) }
  image(path, height: height)
}

// A row of logos on one center line, `gap` apart (the tikz node chain).
#let logo-row(entries, height, gap) = stack(
  dir: ltr,
  spacing: gap,
  ..entries.map(e => box(height: height, align(horizon, logo(e, height)))),
)

// -- inline content -----------------------------------------------------------

#let math-symbols = (
  "→": sym.arrow.r,
  "←": sym.arrow.l,
  "↔": sym.arrow.l.r,
  "⇒": sym.arrow.r.double,
  "⇔": sym.arrow.l.r.double,
  "⟶": sym.arrow.r.long,
  "⟵": sym.arrow.l.long,
  "⟷": sym.arrow.l.r.long,
  "≤": sym.lt.eq,
  "≥": sym.gt.eq,
  "·": sym.dot.c,
)

#let vote-color(yes, no) = if yes > no {
  palette.britishracinggreen
} else if yes < no {
  palette.red
} else {
  palette.eggplant
}

#let inline(nodes) = {
  for n in nodes {
    let t = n.t
    if t == "text" {
      n.v
    } else if t == "strong" {
      strong(inline(n.c))
    } else if t == "emph" {
      emph(inline(n.c))
    } else if t == "strike" {
      strike(inline(n.c))
    } else if t == "code" {
      text(font: mono-font, n.v)
    } else if t == "link" {
      link(n.url, text(fill: palette.hsrturl, inline(n.c)))
    } else if t == "br" {
      linebreak()
    } else if t == "sym" {
      math.equation(block: false, math-symbols.at(n.v, default: n.v))
    } else if t == "math" {
      mi(n.tex)
    } else if t == "time" {
      // pytex asked for the FontAwesome 5 `clock`, which FontAwesome 4 lacks,
      // so only the space in front of the time remains.
      text(fill: palette.hanblue)[ #strong(n.v)]
    } else if t == "vote" {
      let dot = math.equation(block: false, sym.dot.c)
      strong[Abstimmung: ]
      text(fill: vote-color(n.yes, n.no))[Ja #n.yes #dot Nein #n.no #dot Enthaltung #n.abstain]
    } else if t == "image" {
      emph[\[#n.alt\]]
    }
  }
}

// -- boxes (HSRTReport `ColoredBox`) ----------------------------------------

// The nesting depth of the boxes. The tint grows with it.
#let box-depth = state("box-depth", 0)

// The text starts 10pt + 0.25cm + 2pt from the left edge and ends 17.08pt
// from the right edge. The first text line starts 9.63pt below the top edge,
// the last one ends 12.83pt above the bottom edge.
#let box-inset = (left: 19.09pt, right: 17.08pt, top: 9.63pt, bottom: 12.83pt)

// A rounded, tinted box with an icon that hangs over the left edge, 8.28pt
// left of the box plus the horizontal offset of the style.
#let colored-box(color: palette.blue, icon: none, icon-dx: 1.5pt, inset: box-inset, body) = {
  box-depth.update(d => d + 1)
  context {
    let level = box-depth.get()
    // round((0.05 + 0.075 * level) * 100) with Python rounding: 12, 20, 28.
    let bg = (0, 12, 20, 28, 35, 42).at(calc.min(level, 5))
    block(
      width: 100%,
      // A minipage: LaTeX never splits a box across pages.
      breakable: false,
      fill: tint(color, bg * 1%),
      radius: 5pt,
      inset: inset,
      {
        if icon != none {
          place(
            top + left,
            dx: -8.28pt + icon-dx - inset.left,
            dy: icon.top - inset.top,
            text(
              font: icon-font,
              size: 24pt,
              top-edge: "ascender",
              bottom-edge: "descender",
              fill: tint(color, (bg + 20) * 1%),
              icon.glyph,
            ),
          )
        }
        body
      },
    )
  }
  box-depth.update(d => d - 1)
}

#let callout-styles = (
  info: (color: palette.blue, icon: icons.info-circle, dx: 1.5pt),
  warning: (color: palette.red, icon: icons.exclamation-triangle, dx: 0.5pt),
  success: (color: palette.green, icon: icons.check-circle, dx: 1.5pt),
  important: (color: palette.orange, icon: icons.exclamation-circle, dx: 1.5pt),
  decision: (color: palette.britishracinggreen, icon: icons.gavel, dx: 1.5pt),
  task: (color: palette.navyblue, icon: none, dx: 1.5pt),
  deadline: (color: palette.orange, icon: icons.hourglass-half, dx: 1.5pt),
)

// The vote tally: the question over three small boxes in three columns,
// 10pt apart (\columnsep). The question ends 9.28pt above the small boxes,
// which end 8.5pt above the bottom edge.
#let tally(n) = {
  // The cell labels have no descender, so TeX sets the cells lower than a
  // box with running text.
  let cell(label, count, color, icon) = colored-box(color: color, icon: icon, inset: box-inset + (bottom: 11.5pt))[*#label:* #count]
  colored-box(color: vote-color(n.yes, n.no), inset: box-inset + (bottom: 8.5pt), {
    if n.lines.len() > 0 {
      block(n.lines.map(inline).join(linebreak()))
      v(9.28pt)
    }
    grid(
      columns: (1fr, 1fr, 1fr),
      column-gutter: 10pt,
      cell("Ja", n.yes, palette.britishracinggreen, icons.thumbs-up),
      cell("Nein", n.no, palette.red, icons.thumbs-down),
      cell("Enthaltung", n.abstain, palette.eggplant, none),
    )
  })
}

// -- block spacing ----------------------------------------------------------

// The kind of a block node, for the gap table.
#let kind(n) = {
  if n.t == "heading" {
    if n.level >= 4 { "par" } else { "h" + str(n.level) }
  } else if n.t in ("callout", "tally") {
    "box"
  } else if n.t == "codeblock" {
    "code"
  } else if n.t == "mathblock" {
    "math"
  } else if n.t == "signatures" {
    "sig"
  } else {
    n.t
  }
}

// The gap in front of a block after a paragraph (or any block without its
// own row below).
#let gap-after-text = (
  par: 5.79pt,
  h1: 34.31pt,
  h2: 26.76pt,
  h3: 18.4pt,
  runin: 23.24pt,
  list: 8.78pt,
  quote: 8.78pt,
  box: 24.35pt,
  table: 14.85pt,
  code: 4.6pt,
  rule: 16.04pt,
  math: 22.64pt,
  sig: 56.13pt,
)
// The gaps that differ after a particular kind of block.
#let gap-after = (
  h1: (par: 12.72pt, runin: 12.72pt, list: 12.72pt, quote: 12.72pt, box: 31.44pt, table: 13.89pt, code: 11.53pt, rule: 23.14pt, math: 29.54pt, h1: 17.09pt, h2: 14.9pt, h3: 14.9pt),
  h2: (par: 10.64pt, runin: 10.64pt, list: 10.64pt, quote: 10.64pt, box: 29.21pt, table: 14.3pt, code: 9.45pt, rule: 21.06pt, math: 27.44pt, h1: 15.5pt, h2: 13.9pt, h3: 12.81pt),
  h3: (par: 9.56pt, runin: 9.56pt, list: 9.56pt, quote: 9.56pt, box: 28.13pt, table: 13.2pt, code: 8.4pt, rule: 20pt, math: 26.34pt, h1: 13.93pt, h2: 12.9pt, h3: 11.8pt),
  box: (par: 3.61pt, runin: 3.61pt, list: 6.57pt, quote: 6.75pt, box: 14.62pt, table: 17.5pt, code: 3.1pt, rule: 6.5pt, math: 12.74pt, h1: 28.74pt, h2: 23.59pt, h3: 15.68pt, sig: 50pt),
  list: (par: 8.78pt, runin: 8.78pt, box: 27.52pt),
  quote: (par: 8.78pt, runin: 8.78pt, box: 27.58pt),
  table: (par: 14.3pt, runin: 14.3pt, list: 8.98pt, quote: 8.98pt, box: 25.41pt, h1: 31.4pt, h2: 23.89pt, h3: 15.5pt),
  code: (par: 10.95pt, runin: 10.95pt, box: 29.75pt, h1: 39.26pt, h2: 31.7pt, h3: 23.3pt),
  rule: (par: 8.25pt, runin: 8.25pt, box: 26.48pt),
  math: (par: 14.37pt, runin: 14.37pt, box: 33.03pt),
)

#let gap(prev, cur) = {
  let row = gap-after.at(prev, default: (:))
  row.at(cur, default: gap-after-text.at(cur))
}

// -- signatures ---------------------------------------------------------------

#let signatures(signers) = {
  // \section*{Unterschriften}, then two minipages per row (0.46\linewidth,
  // centered): a 5cm rule, the name and the role in \small.
  block(text(font: head-font, size: size.Large, weight: "bold")[Unterschriften])
  v(55.76pt)
  let cell(role, name) = box(width: 46%, align(center, {
    rect(width: 5cm, height: 0.4pt, fill: black, stroke: none)
    v(7.38pt)
    block(if name != "" { name } else { [~] })
    v(1.22pt)
    block(text(size: size.small, role))
  }))
  for (i, row) in signers.chunks(2).enumerate() {
    if i > 0 { v(44.95pt) }
    block(width: 100%, {
      cell(..row.at(0))
      h(1fr)
      if row.len() > 1 { cell(..row.at(1)) }
    })
  }
}

// -- blocks -------------------------------------------------------------------

#let bullet-markers = ([•], [–], [∗], [·])
#let enum-marker(level, n) = if level == 0 {
  [#n.]
} else if level == 1 {
  [(#numbering("a", n))]
} else if level == 2 {
  [#numbering("i", n).]
} else {
  [#numbering("A", n).]
}
// \leftmargini ... \leftmarginiv
#let list-indents = (2.5em, 2.2em, 1.87em, 1.7em)

#let table-block(n) = {
  let aligns = n.align.map(a => if a == "center" { center } else if a == "right" { right } else { left })
  let cols = n.head.len()
  let row(cells) = grid(
    columns: (1fr,) * cols,
    align: aligns,
    inset: (x: 6pt),
    ..range(cols).map(k => {
      set par(justify: false)
      inline(cells.at(k, default: ()))
    }),
  )
  let rule(w) = rect(width: 100%, height: w, fill: black, stroke: none)
  // booktabs at \arraystretch 1.5: \toprule .08em, \midrule .05em,
  // \bottomrule .08em, 20.33pt from row to row.
  block(width: 100%, breakable: false, {
    rule(0.876pt)
    v(6.45pt)
    row(n.head)
    v(5.6pt)
    rule(0.548pt)
    v(6.5pt)
    for (i, r) in n.rows.enumerate() {
      if i > 0 { v(20.33pt - 1.211 * size.normal) }
      row(r)
    }
    v(5.46pt)
    rule(0.876pt)
  })
}

#let code-block(n) = {
  // lstlisting with `frame=single`, `numbers=left` and \footnotesize
  // \ttfamily: the frame sits 3pt outside the text column, the numbers 10pt
  // left of it, and the lines are 10.96pt apart.
  let lines = n.v.split("\n")
  let edges = (top-edge: 7pt, bottom-edge: -2pt)
  block(
    width: 100%,
    stroke: 0.4pt,
    outset: (x: 3.2pt),
    inset: (top: 3.91pt, bottom: 4.39pt, left: 0.5pt),
    breakable: true,
    grid(
      columns: (0pt, 1fr),
      row-gutter: 10.96pt - 9pt,
      ..lines
        .enumerate()
        .map(((k, line)) => (
          place(right, dx: -10pt, text(font: body-font, size: size.footnote, ..edges, str(k + 1))),
          text(font: mono-font, size: size.footnote, tracking: 0.075em, ..edges, if line == "" { [~] } else { h(0.0375em) + raw(line) }),
        ))
        .flatten(),
    ),
  )
}

#let blocks(nodes, in-item: false) = {
  let prev = none
  let i = 0
  while i < nodes.len() {
    let n = nodes.at(i)
    let k = kind(n)
    let runin = n.t == "heading" and n.level >= 4
    let kk = if runin { "runin" } else { k }
    if prev != none {
      let g = if in-item != false and prev == "par" and k == "list" { 8.45pt } else { gap(prev, kk) }
      v(g, weak: true)
    }
    if runin {
      // \paragraph runs into the next paragraph.
      let rest = if i + 1 < nodes.len() and nodes.at(i + 1).t == "par" { nodes.at(i + 1).c } else { () }
      par(text(font: head-font, weight: "bold", inline(n.c)) + h(1em) + inline(rest))
      if rest != () { i += 1 }
    } else if n.t == "heading" {
      heading(level: n.level, inline(n.c))
    } else if n.t == "par" {
      par(inline(n.c))
    } else if n.t == "list" {
      let depth = if in-item == false { 0 } else { in-item }
      let indent = list-indents.at(calc.min(depth, 3))
      for (j, item) in n.items.enumerate() {
        if j > 0 {
          let after-nested = n.items.at(j - 1).len() > 0 and kind(n.items.at(j - 1).last()) == "list"
          v(if after-nested { 8.78pt } else if depth > 0 { 5.47pt } else { 5.79pt }, weak: true)
        }
        let marker = if n.ordered {
          enum-marker(n.at("olevel", default: 0), n.start + j)
        } else {
          bullet-markers.at(calc.min(n.at("ulevel", default: 0), 3))
        }
        grid(
          columns: (indent, 1fr),
          // \labelsep 0.5em; LaTeX sets an enumerate label another 2.42pt
          // further left than a bullet.
          align(right, pad(right: if n.ordered { 0.5em + 2.42pt } else { 0.5em }, marker)),
          blocks(item, in-item: depth + 1),
        )
      }
    } else if n.t == "quote" {
      pad(x: 2.5em, blocks(n.c))
    } else if n.t == "callout" {
      let style = callout-styles.at(n.kind)
      colored-box(color: style.color, icon: style.icon, icon-dx: style.dx, blocks(n.c))
    } else if n.t == "tally" {
      tally(n)
    } else if n.t == "codeblock" {
      code-block(n)
    } else if n.t == "rule" {
      rect(width: 100%, height: 0.4pt, fill: black, stroke: none)
    } else if n.t == "table" {
      table-block(n)
    } else if n.t == "mathblock" {
      mitex(n.tex)
    } else if n.t == "signatures" {
      signatures(n.signers)
    }
    prev = kk
    i += 1
  }
}

// -- pages --------------------------------------------------------------------

#let skyline = place(bottom + left, image(vendored-logos.Skyline, width: 1.5 * 210mm))

#let title-page(doc) = page(
  margin: 2cm,
  background: skyline,
  foreground: none,
  {
    // The first logo sits 2cm from the left and 1.5cm from the top edge,
    // 1.4cm high; the next ones follow 0.5cm apart.
    if doc.logos.len() > 0 {
      place(top + left, dy: 1.5cm - 2cm, logo-row(doc.logos, 1.4cm, 0.5cm))
    }
    v(4cm + 27.7pt)
    block(below: 0pt, par(leading: 20.04pt - 24.88pt, justify: false, text(
      font: head-font,
      size: size.Huge,
      weight: "bold",
      hyphenate: false,
      doc.title,
    )))
    v(5pt)
    rect(width: 100%, height: 0.5mm, fill: black, stroke: none)
    v(1fr)
    // tabular{@{} p{30mm} p{...} @{}}, 20.33pt from row to row. The label
    // column widens for a long label instead of running into the value.
    context {
      let widths = doc.data.map(r => measure(strong(r.at(0))).width)
      let label-width = calc.max(30mm, ..widths) + 12pt
      grid(
        columns: (label-width, 1fr),
        row-gutter: 20.33pt - 1.211 * size.normal,
        ..doc.data.map(r => (strong(r.at(0)), r.at(1))).flatten(),
      )
    }
    v(-6.6pt)
  },
)

#let protocol(doc) = {
  set document(title: doc.title)
  set text(
    font: body-font,
    size: size.normal,
    lang: "de",
    hyphenate: true,
    top-edge: "ascender",
    bottom-edge: "descender",
  )
  // Every gap between blocks comes from the gap table, so the blocks carry
  // no spacing of their own.
  set par(justify: true, leading: leading, spacing: 0pt, first-line-indent: 0pt)
  set block(above: 0pt, below: 0pt)
  set strong(delta: 300)
  show math.equation: set text(font: math-font)
  show math.equation.where(block: true): set block(above: 0pt, below: 0pt)

  // Section headings: Blender bold, "TOP n" and "TOP n.m", then \enskip.
  set heading(numbering: (..n) => {
    let n = n.pos()
    if n.len() == 1 { [TOP #n.at(0)] } else if n.len() == 2 { [TOP #n.at(0).#n.at(1)] }
  })
  show heading: it => {
    let sz = if it.level == 1 { size.Large } else { size.large }
    set text(font: head-font, weight: "bold", size: sz)
    set par(justify: false)
    block(sticky: true, {
      if it.numbering != none and it.level <= 2 {
        counter(heading).display(it.numbering)
        h(0.5em)
      }
      it.body
    })
  }

  // The running head and the page number sit at fixed page positions, as the
  // KOMA page styles put them. The footer logos end 2.3cm from the right edge.
  let frame = context {
    let page-no = counter(page).get().first()
    let last = counter(page).final().first()
    set text(font: head-font, size: size.normal, fill: palette.gray)
    place(top + left, dx: 2cm, dy: 29.09pt, doc.title)
    place(top + center, dy: 798.53pt, [Seite~#page-no~von~#text(fill: palette.hsrtlink, str(last))])
  }
  let footer-logos = if doc.footer_logos.len() > 0 {
    place(bottom + right, dx: -2.3cm, dy: -(1.5 * size.normal + 2pt), logo-row(doc.footer_logos, 0.8cm, 0.3cm))
  }
  set page(
    paper: "a4",
    // The body starts 5.18pt below the 2cm margin, as in pytex.
    margin: (top: 2cm + 5.18pt, rest: 2cm),
    header: none,
    footer: none,
    background: skyline + footer-logos,
    foreground: frame,
  )

  title-page(doc)
  counter(page).update(1)
  blocks(doc.body)
}
