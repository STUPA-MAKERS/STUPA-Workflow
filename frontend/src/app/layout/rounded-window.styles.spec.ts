/**
 * Style contract of the rounded sheets beside the rail. jsdom does no layout, so this
 * spec reads the styles. A large sheet with round corners clips what scrolls in it only
 * when the rounded element is the scroll container (or an `overflow: hidden` parent of
 * it). A rounded child inside a rectangular scroll box, or a sheet that scrolls with the
 * window, is cut by straight lines at the window edges.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const app = join(__dirname, '..');
const read = (path: string): string => readFileSync(join(app, path), 'utf8');

const shell = read('layout/shell.component.scss');
const listDetail = read('shared/ui/list-detail/list-detail-layout.component.scss');
const adminFrame = read('pages/admin/admin-frame/admin-frame.component.scss');
const budget = read('pages/budget/budget-dashboard.component.scss');
const globalStyles = readFileSync(join(app, '../styles.scss'), 'utf8');

/** The declarations of the first rule with exactly this selector. */
function rule(css: string, selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`(?:^|\\n)\\s*${esc} \\{([^}]*)\\}`));
  if (!m) throw new Error(`No rule ${selector}`);
  return m[1];
}

describe('rounded sheet styles', () => {
  it('rounds the detail pane of the list/detail layout, which is the scroll container', () => {
    const pane = rule(listDetail, ':host(.ld--split) .ld__detail');
    expect(pane).toMatch(/border-radius: var\(--ld-detail-radius, var\(--radius-2xl\)\);/);
    expect(rule(listDetail, '.ld__list,\n.ld__detail')).toMatch(/overflow-y: auto;/);
  });

  it('makes the admin sheet clip and its body scroll', () => {
    const sheet = rule(adminFrame, '.af--split .af__page');
    expect(sheet).toMatch(/overflow: hidden;/);
    expect(sheet).toMatch(/border-radius: var\(--radius-2xl\);/);
    expect(rule(adminFrame, '.af--split .af__pageBody')).toMatch(/overflow-y: auto;/);
  });

  it('keeps the budget sheet clipping', () => {
    expect(rule(budget, '.bd--wide .bd__sheet')).toMatch(/overflow: hidden;/);
  });

  it('gives a pane page the gutter as the gap at the bottom and at the top', () => {
    expect(rule(shell, '.main')).toMatch(/--pane-foot-gap: var\(--layout-gutter\);/);
    expect(rule(shell, '.frame--rail .main')).toMatch(/--main-pad-top: var\(--layout-gutter\);/);
    expect(rule(shell, '.frame--rail .main.main--fill')).toMatch(
      /--main-pad-bottom: var\(--pane-foot-gap\);/,
    );
    expect(rule(globalStyles, '.pane-page')).toMatch(
      /margin-bottom: calc\(var\(--pane-foot-gap, 0px\) - var\(--main-pad-bottom, 0px\)\);/,
    );
  });

  it('gives the admin frame no width cap, so its column starts next to the rail', () => {
    expect(rule(adminFrame, '.af')).not.toMatch(/max-width|margin-inline: auto/);
  });
});
