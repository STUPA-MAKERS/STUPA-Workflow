/**
 * App specs 000614 to 000623: the controls that the app draws itself take the forms of very
 * high contrast (`shared/ui/_very-high-contrast.scss`), and no script of the app moves content
 * without the motion setting. jsdom applies no styles, so this spec reads the sources.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const APP = join(__dirname, '..');
const RULES = readFileSync(join(__dirname, 'ui/_very-high-contrast.scss'), 'utf8');
const GLOBAL = readFileSync(join(APP, '../styles.scss'), 'utf8');

/** The selector list in front of the first use of this form after `anchor`. */
function selectorsOf(anchor: string, form: string): string {
  const start = RULES.indexOf(anchor);
  if (start < 0) throw new Error(`No rule ${anchor}`);
  return RULES.slice(start, RULES.indexOf(`@include vh.${form};`, start));
}

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return name.endsWith('.ts') && !name.endsWith('.spec.ts') ? [path] : [];
  });
}

describe('veryHighContrastApp (§000614)', () => {
  it('the global stylesheet loads the rules, inside the setting', () => {
    expect(GLOBAL).toContain("@use './app/shared/ui/very-high-contrast';");
    expect(RULES).toMatch(/@include d\.on\(veryHigh\) \{/);
  });
});

describe('surfaceEdges (§000605)', () => {
  it('draws the white edge around the calendar grid, its day pane and the pane of the start page', () => {
    expect(RULES).toMatch(/\.dash--wide \.dash__today,\s*\.cal__panel \{\s*outline: var\(--vh-edge\);\s*outline-offset: -2px;/);
    expect(RULES).toMatch(/\.cal__grid::after \{[^}]*border: var\(--vh-edge\);/);
  });

  it('draws the white edge around a meeting in the day pane of the calendar', () => {
    expect(RULES).toMatch(/\.cal__panel \.cal__card \{[^}]*border: var\(--vh-edge\);/);
  });

  it('draws the white edge around a card and a column of a board', () => {
    expect(RULES).toMatch(
      /\n {2}app-todo-card-tile,\s*\.bv__col \{\s*outline: var\(--vh-edge\);\s*outline-offset: -2px;/,
    );
  });

  it('keeps the top edge of the work list of the start page above its sticky header', () => {
    const rule = /\.dash--wide \.dash__panel:has\(\.dt--boxed\)::before \{([^}]*)\}/.exec(RULES)?.[1] ?? '';
    expect(rule).toMatch(/position: sticky;\s*top: 0;/);
    expect(rule).toMatch(/border: var\(--vh-edge\);\s*border-bottom: 0;/);
    expect(rule).toMatch(/pointer-events: none;/);
  });
});

describe('boardPicker (§000617)', () => {
  it('draws the picker as a menu: white edge, yellow rows, the open board filled', () => {
    expect(RULES).toMatch(/\.bp__pop \{\s*outline: var\(--vh-edge\);\s*outline-offset: -2px;/);
    expect(RULES).toMatch(/\n {2}\.bp__row \{\s*@include vh\.text;/);
    expect(RULES).toMatch(/\.bp__row\[aria-current='true'\] \{\s*@include vh\.fill;/);
    expect(RULES).toMatch(/\.bp__cap \{\s*color: var\(--vh-fg\) !important;/);
  });

  it('marks the row under the pointer with a yellow edge, not with a fill', () => {
    expect(RULES).toMatch(
      /@media \(hover: hover\) \{\s*\.bp__row:hover \{\s*outline: 2px solid var\(--vh-hi\) !important;/,
    );
  });
});

describe('protocolBand (§000605, §000614)', () => {
  it('gives the band of the protocol white ink on its black surface, the edge, and filled PDF buttons', () => {
    expect(RULES).toMatch(/\n {2}\.pb \{\s*@include vh\.ink\(var\(--vh-fg\)\);\s*outline: var\(--vh-edge\);/);
    expect(selectorsOf('  .pb__pdf {', 'fill')).toContain('.pb__pdf');
  });
});

describe('menuRows (§000617)', () => {
  it('gives the rows of the help menu yellow text', () => {
    expect(selectorsOf('  .hm__item {', 'text')).toContain('.hm__item');
  });
});

describe('choiceCards (§000618)', () => {
  it('gives a vote option, an option for a represented person and a type card the yellow edge', () => {
    const edge = selectorsOf('  .choice,', 'edge');
    for (const card of ['.choice', '.pchoice', '.wz__type']) expect(edge).toContain(card);
  });

  it('fills the chosen card', () => {
    const fill = selectorsOf('  .choice--on,', 'fill');
    for (const card of ['.choice--on', '.pchoice--on', '.wz__type.is-selected']) expect(fill).toContain(card);
  });

  it('keeps the circle: in the ink of the card, black with a yellow tick when chosen', () => {
    expect(RULES).toMatch(/\.choice__mark \{\s*box-shadow: inset 0 0 0 2px var\(--vh-ink\) !important;/);
    expect(RULES).toMatch(
      /\.choice--on \.choice__mark \{\s*background: var\(--vh-bg\) !important;\s*color: var\(--vh-hi\) !important;/,
    );
  });
});

describe('rowsAndFills (§000619, §000621)', () => {
  it('gives a day of the calendar a yellow number', () => {
    expect(RULES).toMatch(/\.cal__num:not\(\.cal__num--today\) \{\s*color: var\(--vh-hi\) !important;/);
  });

  it('fills the open page and the chosen tile of the admin frame', () => {
    const fill = selectorsOf('  .af__item--on,', 'fill');
    expect(fill).toContain('.ah__tile--on');
  });

  it('turns the text of the chosen budget node black', () => {
    expect(RULES).toMatch(/\.tn--on \{\s*@include vh\.ink\(var\(--vh-bg\), var\(--vh-bg\)\);/);
  });
});

describe('copyBoxes (§000739)', () => {
  it('fills the address of a calendar subscription and the boxes of the MCP setup', () => {
    const fill = selectorsOf('  .cs__url,', 'fill');
    expect(fill).toContain('.gr__cmd');
    expect(fill).toContain('.gr__config');
  });
});

describe('permissionChips (§000615, §000620)', () => {
  it('fills a granted permission and gives the others the edge', () => {
    expect(selectorsOf('  .rm__chip--on {', 'fill')).toContain('.rm__chip--on');
    expect(selectorsOf('  .rm__chip:not(', 'edge')).toContain('.rm__chip:not(.rm__chip--on, .rm__chip--off)');
  });
});

describe('scriptsReadMotionSetting (§000623)', () => {
  const files = sources(APP);

  it('no script of the app reads the system motion setting itself', () => {
    const offenders = files.filter((f) => /prefers-reduced-motion/.test(readFileSync(f, 'utf8')));
    expect(offenders).toEqual([]);
  });

  it('no script of the app starts a smooth scroll without the motion setting', () => {
    const offenders = files.filter((f) => /behavior:\s*['"]smooth['"]/.test(readFileSync(f, 'utf8')));
    expect(offenders).toEqual([]);
  });
});
