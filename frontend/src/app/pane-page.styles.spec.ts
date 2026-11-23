/**
 * Style contract of the pane pages (spec 001930). jsdom does no layout, so this spec reads the
 * sources. A pane page (`pane-page`, `injectPanePage`) is one window high and the frame of the
 * shell is too. The rail sticks only inside that frame. When nothing in the page scrolls by
 * itself, a long list grows past the window, the window scrolls, and the rail scrolls away with
 * the page. So every pane page must have a scroll container of its own.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';

const app = __dirname;

function sources(dir: string): readonly string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return name.endsWith('.component.ts') ? [path] : [];
  });
}

/** The template and the styles of a component, as one text. */
function view(ts: string): string {
  const src = readFileSync(ts, 'utf8');
  const dir = dirname(ts);
  const files = [
    ...[...src.matchAll(/templateUrl:\s*'([^']+)'/g)].map((m) => m[1]),
    ...[...src.matchAll(/styleUrl:\s*'([^']+)'/g)].map((m) => m[1]),
    ...[...src.matchAll(/styleUrls:\s*\[([^\]]*)\]/g)].flatMap((m) =>
      [...m[1].matchAll(/'([^']+)'/g)].map((n) => n[1]),
    ),
  ];
  return files.map((file) => readFileSync(join(dir, file), 'utf8')).join('\n');
}

const panePages = sources(app).filter((ts) =>
  /'\[class\.pane-page\]'|injectPanePage\(/.test(readFileSync(ts, 'utf8')),
);

/** A scroll container of the page itself, or a kit layout or kit view that brings one. */
const scroller =
  /overflow-y: auto|overflow: auto|lp\.split-scroll|<app-list-detail\b|<app-tab-pager\b|<app-form-editor-view\b/;

describe('pane page styles (001930)', () => {
  it('finds the pane pages', () => {
    expect(panePages.map((ts) => ts.slice(app.length + 1))).toContain(
      'pages/activity/activity.component.ts',
    );
  });

  it.each(panePages.map((ts) => [ts.slice(app.length + 1), ts]))(
    '%s has a scroll container of its own, so the window and the rail stay put',
    (_name, ts) => {
      expect(view(ts)).toMatch(scroller);
    },
  );

  it('lets the activity list scroll inside the pane page', () => {
    const css = readFileSync(join(app, 'pages/activity/activity.component.scss'), 'utf8');
    expect(css).toMatch(/:host\(\.pane-page\) \.act__scroll \{\s*@include lp\.split-scroll\(--act-fade\);/);
    expect(css).toMatch(
      /:host\(\.pane-page\) \.act,\n:host\(\.pane-page\) \.act > \.ld-pane \{[^}]*flex: 1 1 0;[^}]*min-height: 0;/,
    );
  });
});
