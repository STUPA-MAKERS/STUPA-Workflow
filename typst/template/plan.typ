// The layout of one version of a Haushaltsplan: A4 landscape, a head with the
// data of the version, and one table that breaks across pages with its
// headings repeated. The service sends each cell as text, so the PDF prints
// the figures of the platform and computes none.
#import "protocol.typ": body-font, head-font, logo-row, palette, size, tint

#let plan-size = 8.5pt

// One row of the table as cells. A group heading spans the table. A sum and
// the balance print bold below a thin rule.
#let plan-row(row, cols) = {
  let cells = row.cells
  if row.kind == "group" {
    (
      table.cell(colspan: cols, fill: tint(palette.gray, 18%), inset: (x: 4pt, y: 4pt), text(
        font: head-font,
        weight: "bold",
        size: size.small,
        cells.at(1),
      )),
    )
  } else if row.kind == "line" {
    range(cols).map(i => if i == 1 { pad(left: row.depth * 0.9em, cells.at(i)) } else { cells.at(i) })
  } else {
    (
      table.hline(stroke: 0.4pt),
      ..range(cols).map(i => strong(cells.at(i))),
      ..if row.kind == "balance" { (table.hline(stroke: 0.876pt),) },
    )
  }
}

#let plan(doc) = {
  let p = doc.plan
  let cols = p.headers.len()
  set document(title: p.title)
  set text(
    font: body-font,
    size: plan-size,
    lang: "de",
    hyphenate: true,
  )
  set par(justify: false, leading: 0.5em)
  set strong(delta: 300)

  // The running head names the plan on each page. A version that is not in
  // force carries its state there, so no page reads like a decided plan.
  let running = {
    set text(font: head-font, size: size.small, fill: palette.gray)
    grid(
      columns: (1fr, auto),
      p.title,
      if p.mark != "" { text(weight: "bold", fill: palette.red, upper(p.mark)) },
    )
  }
  let foot = context {
    let page-no = counter(page).get().first()
    let last = counter(page).final().first()
    set text(font: head-font, size: size.small, fill: palette.gray)
    grid(
      columns: (1fr, auto, 1fr),
      align: (left + horizon, center + horizon, right + horizon),
      [],
      [Seite~#page-no~von~#text(fill: palette.hsrtlink, str(last))],
      if doc.footer_logos.len() > 0 { logo-row(doc.footer_logos, 0.6cm, 0.3cm) },
    )
  }
  set page(
    paper: "a4",
    flipped: true,
    margin: (top: 2cm, bottom: 1.9cm, x: 1.5cm),
    header: running,
    header-ascent: 0.7cm,
    footer: foot,
    footer-descent: 0.6cm,
  )

  if doc.logos.len() > 0 {
    logo-row(doc.logos, 1.1cm, 0.5cm)
    v(0.5cm)
  }
  block(below: 4pt, text(font: head-font, size: size.Huge * 0.72, weight: "bold", hyphenate: false, p.title))
  rect(width: 100%, height: 0.5mm, fill: black, stroke: none)
  v(0.15cm)
  {
    set text(size: size.small * 0.85)
    grid(
      columns: (auto,) * (2 * p.head.len()),
      column-gutter: (0.45em, 1.6em) * p.head.len(),
      ..p.head.map(pair => (text(fill: palette.gray, pair.at(0)), strong(pair.at(1)))).flatten(),
    )
  }
  v(0.25cm)

  let money = p.money
  table(
    columns: range(cols).map(i => if i == 1 { 2.2fr } else if i == cols - 1 { 2fr } else { auto }),
    align: (x, y) => if money.contains(x) { right + top } else { left + top },
    stroke: none,
    inset: (x: 4pt, y: 3pt),
    table.hline(stroke: 0.876pt),
    table.header(..p.headers.map(h => text(font: head-font, weight: "bold", h))),
    table.hline(stroke: 0.548pt),
    ..p.rows.map(row => plan-row(row, cols)).flatten(),
    table.hline(stroke: 0.876pt),
  )
}
