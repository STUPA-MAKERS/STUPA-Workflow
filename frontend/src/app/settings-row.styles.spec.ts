import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

/**
 * §ui-kit:000631: a settings row is a child of the shared settings row group. The stylesheet of
 * the page sets no height, surface or corners for the row. A page on `app-settings-screen` without
 * an own row group (Konto Benachrichtigungen) gets the group from the kit (§ui-kit:002244). Every
 * switch of Verwaltung, also in a dialog, is such a row; a switch in the end slot (`trail`) of a
 * record row is the exception, because that row already is a row of a group.
 */
const PAGES = [
  { name: 'pages/admin/notifications/notification-settings.component', row: 'ns__row' },
  { name: 'pages/admin/help-tickets/help-tickets.component', row: 'ht__row' },
  { name: 'pages/admin/branding/branding-editor.component', row: 'br__skSwitch' },
];

const read = (rel: string): string => readFileSync(join(__dirname, rel), 'utf8');

/** The declarations of every rule whose selector names the class `row`. */
function declarationsOf(scss: string, row: string): string {
  const rule = new RegExp(`[^{}]*\\.${row}\\b[^{}]*\\{([^{}]*)\\}`, 'g');
  return [...scss.matchAll(rule)].map((m) => m[1]).join('\n');
}

describe('SettingsRows', () => {
  it.each(PAGES)('$name lists its settings in the shared settings row group', ({ name }) => {
    expect(read(`${name}.html`)).toMatch(/class="rowgroup rowgroup--settings\b/);
  });

  it.each(PAGES)('$name sets no height, surface or corners for the row', ({ name, row }) => {
    const rules = declarationsOf(read(`${name}.scss`), row);
    expect(rules).not.toMatch(/min-height|background|border-radius/);
  });
});

const ADMIN = 'pages/admin';
/** The flow inspectors move into the kit views (§ui-kit:002277), which carry the row group. */
const SKIP = /^flow\//;
const TAG = /<(\/?)([a-zA-Z][\w-]*)((?:[^>"']|"[^"]*"|'[^']*')*?)(\/?)>/g;
const VOID = new Set(['input', 'img', 'br', 'hr', 'meta', 'link', 'source', 'col', 'wbr']);

interface Frame {
  readonly name: string;
  readonly attrs: string;
}

const GROUP = /class="rowgroup rowgroup--settings\b/;
const TRAIL = /\strail(\s|=|$)/;

/**
 * True when the switch is a settings row or sits in one (a label, a choice and a switch), or
 * sits in the end slot of a record row (`trail` on the switch or on its parent).
 */
const placed = (stack: readonly Frame[], attrs: string): boolean =>
  stack.some((f) => GROUP.test(f.attrs)) ||
  TRAIL.test(` ${attrs}`) ||
  TRAIL.test(` ${stack.at(-1)?.attrs ?? ''}`);

/** The opening tags of the switches that are neither in a settings row group nor in a trail slot. */
function looseSwitches(html: string): readonly string[] {
  return [...html.matchAll(TAG)].reduce<{ stack: readonly Frame[]; loose: readonly string[] }>(
    (acc, [whole, close, name, attrs, self]) => {
      if (close) {
        const at = acc.stack.map((f) => f.name).lastIndexOf(name);
        return at < 0 ? acc : { ...acc, stack: acc.stack.slice(0, at) };
      }
      const loose =
        name === 'app-switch' && !placed(acc.stack, attrs) ? [...acc.loose, whole] : acc.loose;
      const stack = self || VOID.has(name) ? acc.stack : [...acc.stack, { name, attrs }];
      return { stack, loose };
    },
    { stack: [], loose: [] },
  ).loose;
}

const TEMPLATES = readdirSync(join(__dirname, ADMIN), { recursive: true, encoding: 'utf8' })
  .filter((f) => f.endsWith('.html') && !SKIP.test(f))
  .sort();

describe('SettingsRows in Verwaltung', () => {
  it('finds the templates', () => {
    expect(TEMPLATES.length).toBeGreaterThan(10);
  });

  it.each(TEMPLATES)('%s puts every switch in a settings row group', (file) => {
    expect(looseSwitches(read(`${ADMIN}/${file}`))).toEqual([]);
  });

  it('reads a loose switch and a switch in a trail slot', () => {
    expect(looseSwitches('<div class="x"><app-switch a="1">L</app-switch></div>')).toHaveLength(1);
    expect(looseSwitches('<span trail class="x"><app-switch>L</app-switch></span>')).toEqual([]);
    expect(
      looseSwitches('<app-list-item><app-switch trail>L</app-switch></app-list-item>'),
    ).toEqual([]);
    expect(
      looseSwitches('<div class="rowgroup rowgroup--settings"><div class="r"><app-switch /></div></div>'),
    ).toEqual([]);
    expect(
      looseSwitches('<div class="rowgroup rowgroup--settings"><input /><app-switch>L</app-switch></div>'),
    ).toEqual([]);
  });
});
