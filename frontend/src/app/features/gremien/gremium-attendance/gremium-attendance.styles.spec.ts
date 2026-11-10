/**
 * App specs 000609 and 000612: the look of the attendance matrix. jsdom applies no
 * component styles, so this spec reads the stylesheet.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const CSS = readFileSync(join(__dirname, 'gremium-attendance.component.scss'), 'utf8');

/** The declarations of every rule whose selector line is this selector. */
function rule(css: string, selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const all = [...css.matchAll(new RegExp(`(?:^|\\n)\\s*${esc} \\{([^}]*)\\}`, 'g'))];
  if (all.length === 0) throw new Error(`No rule ${selector}`);
  return all.map((m) => m[1]).join('\n');
}

/** The body of the first `@include d.host-on(<setting>) { … }` block. */
function block(setting: string): string {
  const start = CSS.indexOf(`@include d.host-on(${setting}) {`);
  if (start < 0) throw new Error(`No block ${setting}`);
  const end = CSS.indexOf('\n}\n', start);
  return CSS.slice(start, end);
}

describe('rowGroupLook (§NF/usability/layout/000609)', () => {
  it('draws no box, no bar and no cell lines', () => {
    expect(rule(CSS, '.gat__frame')).not.toMatch(/background|border-radius/);
    expect(CSS).not.toMatch(/border-top:/);
    expect(rule(CSS, 'thead .gat__th')).toMatch(/background: var\(--gat-page\);/);
    expect(rule(CSS, 'tfoot .gat__foot')).toMatch(/background: var\(--gat-page\);/);
  });

  it('paints the persons as the rows of a row group on surface 2', () => {
    expect(rule(CSS, '.gat__mx')).toMatch(/border-spacing: 0 2px;/);
    expect(CSS).toMatch(/tbody \.gat__who,\ntbody \.gat__td \{[^}]*background: var\(--color-surface-2\);/);
    expect(rule(CSS, 'tbody tr:first-child .gat__who')).toMatch(/border-start-start-radius: var\(--radius-lg\);/);
    expect(rule(CSS, 'tbody tr:last-child .gat__td:last-child')).toMatch(/border-end-end-radius: var\(--radius-lg\);/);
  });

  it('sets the column titles in small capitals', () => {
    expect(CSS).toMatch(/\.gat__th--name,\n\.gat__month,\n\.gat__sortBtn \{[^}]*text-transform: uppercase;/);
  });

  it('makes a count cell a pill of at most 6 rem', () => {
    const cell = rule(CSS, '.gat__cell');
    expect(cell).toMatch(/max-width: 6rem;/);
    expect(cell).toMatch(/border-radius: var\(--radius-pill\);/);
  });
});

describe('veryHighContrast (§NF/accessibility/settings/000612)', () => {
  it('paints a cell and the sort button black on yellow with the black edge', () => {
    const fields = block('fields');
    expect(fields).toMatch(/button\.gat__cell,\n {2}\.gat__sortBtn \{[^}]*background: var\(--field-bg\);[^}]*color: var\(--field-text\);[^}]*box-shadow: var\(--field-edge\);/);
    expect(fields).toMatch(/button\.gat__cell \.gat__ex \{[^}]*background: var\(--field-text\);[^}]*color: var\(--field-bg\);/);
  });

  it('hides the colour steps of the legend', () => {
    expect(block('fields')).toMatch(/\.gat__legendTone \{\s*display: none;/);
  });

  it('draws the white edge of a row group round the rows', () => {
    const vh = block('veryHigh');
    expect(vh).toMatch(/\.gat__mx \{\s*border-spacing: 0;/);
    expect(vh).toMatch(/tbody tr:first-child \.gat__who \{\s*box-shadow: inset 2px 2px 0 var\(--color-text\);/);
    expect(vh).toMatch(/tbody tr:last-child \.gat__td:last-child \{\s*box-shadow: inset -2px -2px 0 var\(--color-text\);/);
  });

  it('draws a cell of a phone card as white text with a white edge', () => {
    expect(block('veryHigh')).toMatch(
      /\.gat__cell--sm:not\(\.gat__cell--none, \.gat__cell--na\) \{\s*background: transparent;\s*color: var\(--color-text\);\s*box-shadow: inset 0 0 0 2px var\(--color-text\);/,
    );
  });
});
