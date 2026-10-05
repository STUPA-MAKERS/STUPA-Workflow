/**
 * ONE list/detail geometry (DECISIONS, 2026-10-05).
 *
 * Every page with a list or a navigation column beside a sheet uses the same column
 * width, the same gap to the sheet, the same header (`app-page-header` with `pane`) and
 * the same search bar under it. The pages drifted apart once (columns of 304, 340, 384
 * and 440px, titles at x 124, 120 and 136, search fields of 44 and 52px), because each
 * page had a copy of the header and its own width.
 *
 * jsdom applies no styles, so this spec reads the sources. It fails when a page sets the
 * shared width or gap itself, when a list column has a header of its own, or when a page
 * styles the shared header from outside.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '../../../..');
const APP = join(SRC, 'app');
const GLOBAL_STYLES = join(SRC, 'styles.scss');
const PAGE_HEADER_DIR = join(APP, 'shared/ui/page-header');

/**
 * The list pages known when the geometry was unified. The spec finds the list pages by
 * itself (every template with `app-list-detail`); this list only proves that the search
 * still finds them, so a broken search cannot pass with no pages at all.
 */
const KNOWN_LIST_PAGES = [
  'pages/applications/applications-list.component',
  'pages/tasks/tasks.component',
  'features/voting/voting-page/voting.component',
  'features/meetings/meetings-list/meetings-list.component',
  'pages/expenses/expenses.component',
  'pages/invoices/invoices.component',
];
/** Pages with a column of their own beside a sheet (no `app-list-detail`). */
const COLUMN_PAGES = [
  'pages/budget/budget-dashboard.component',
  'pages/admin/admin-frame/admin-frame.component',
];
/** The calendar view of the meetings: no column, but the same header as the list view. */
const HEADER_ONLY_PAGES = ['features/meetings/meetings-calendar/meetings-calendar.component'];

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)],
  );
}

/** The source without comments, so a comment that names a token does not count. */
function code(path: string): string {
  return readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    .replace(/<!--[\s\S]*?-->/g, '');
}

const read = (base: string, ext: 'html' | 'scss') => code(join(APP, `${base}.${ext}`));
const appStyles = () => files(APP).filter((f) => f.endsWith('.scss'));

/** Every page with a list column: the templates that use `app-list-detail`. */
const LIST_PAGES = files(APP)
  .filter((f) => f.endsWith('.component.html') && /<app-list-detail[\s>]/.test(code(f)))
  .map((f) => relative(APP, f).replace(/\.html$/, ''))
  .sort();

describe('the one list/detail geometry', () => {
  it('finds every list page by itself', () => {
    expect(LIST_PAGES).toEqual(expect.arrayContaining(KNOWN_LIST_PAGES));
  });

  it('the list column does not read the state class of the layout', () => {
    // `.ld--split` belongs to app-list-detail. The column gets its height through
    // `--ld-pane-height`, which the layout sets on its list slot while it splits.
    const global = code(GLOBAL_STYLES);
    expect(global).not.toMatch(/\.ld--split[^{]*\.ld-pane/);
    expect(global).toMatch(/\.ld-pane\s*\{[^}]*height:\s*var\(--ld-pane-height,\s*auto\)/);
    const layout = code(join(APP, 'shared/ui/list-detail/list-detail-layout.component.scss'));
    expect(layout).toMatch(/:host\(\.ld--split\) \.ld__list \{[^}]*--ld-pane-height:\s*100%/);
  });

  it('defines the column width and the gap once, in styles.scss', () => {
    const global = code(GLOBAL_STYLES);
    expect(global).toMatch(/--ld-list-width:\s*clamp\(/);
    expect(global).toMatch(/--ld-gap:/);
  });

  it('no component sets the column width or the gap itself', () => {
    const offenders = appStyles().filter((f) => /--ld-(list-width|gap)\s*:/.test(code(f)));
    expect(offenders.map((f) => relative(APP, f))).toEqual([]);
  });

  it('the list-detail layout reads the tokens and has no default of its own', () => {
    const scss = code(join(APP, 'shared/ui/list-detail/list-detail-layout.component.scss'));
    expect(scss).toContain('width: var(--ld-list-width)');
    expect(scss).toContain('gap: var(--ld-gap)');
  });

  it.each(COLUMN_PAGES)('%s puts its column on the shared width and gap', (base) => {
    const scss = read(base, 'scss');
    expect(scss).toMatch(/grid-template-columns:\s*var\(--ld-list-width\)\s+minmax\(0,\s*1fr\)/);
    expect(scss).toMatch(/gap:\s*var\(--ld-gap\)/);
    // No fixed column width next to it (19rem, 24rem and 340px were the old ones).
    expect(scss).not.toMatch(/grid-template-columns:\s*[\d.]+(px|rem)\b/);
  });

  it.each([...LIST_PAGES, ...COLUMN_PAGES])('%s uses the shared column and pane header', (base) => {
    const html = read(base, 'html');
    expect(html).toMatch(/class="ld-pane[\s"]/);
    expect(html).toMatch(/<app-page-header\s[^>]*\[pane\]="true"/);
  });

  it.each([...LIST_PAGES, ...HEADER_ONLY_PAGES])('%s has no list header of its own', (base) => {
    // The h1 is the one of app-page-header. Only the phone bar of the bulk actions of the
    // bookings is an h1 of its own: it replaces the header while rows are selected.
    const html = read(base, 'html').replace(/<header class="exp__selBar"[\s\S]*?<\/header>/, '');
    expect(html).not.toMatch(/<h1[\s>]/);
    expect(html).toMatch(/<app-page-header\s[^>]*\[pane\]="true"/);
    // A local title in the d2 size is a copy of the shared header.
    expect(read(base, 'scss')).not.toContain('--fs-d2');
  });

  it.each(LIST_PAGES)('%s puts its search into the shared filter bar', (base) => {
    const html = read(base, 'html');
    if (!html.includes('<app-search-pill')) return; // the tasks have no search
    expect(html).toMatch(/<app-sticky-bar class="ld-pane__filters[\s"]/);
    // The large field of every list column (a phone may keep the compact one).
    expect(html).not.toMatch(/<app-search-pill\s+size="md"/);
  });

  it('no component styles the shared header from outside', () => {
    // A rule that reaches into the header (its `.ph__*` parts or its `.ph--*` modes)
    // would move the title on one page only. Styling a control that a page projects into
    // the header (`app-page-header app-button …`) is the page's own business.
    const intoHeader = /app-page-header[^{};]*\.ph(__|--)|::ng-deep\s*\.ph(__|--)(bar|text|heading|title|meta|subtitle|actions|pane|flush|rail)/;
    const offenders = appStyles()
      .filter((f) => !f.startsWith(PAGE_HEADER_DIR))
      .filter((f) => intoHeader.test(code(f)));
    expect(offenders.map((f) => relative(APP, f))).toEqual([]);
  });

  it('only the Verwaltung frame moves the header inset, and only in one column', () => {
    const offenders = appStyles()
      .filter((f) => /--ph-inset\s*:/.test(code(f)))
      .map((f) => relative(APP, f));
    expect(offenders).toEqual(['pages/admin/admin-frame/admin-frame.component.scss']);
    const scss = read('pages/admin/admin-frame/admin-frame.component', 'scss');
    expect(scss).toMatch(/\.af:not\(\.af--split\)\s*\{\s*--ph-inset:/);
  });
});
