/**
 * A scroll event runs no change detection (spec 002160): no template binds `(scroll)`, and no
 * host binds `scroll` or `window:scroll`. A component listens with a native passive listener.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const FRONTEND = join(__dirname, '..', '..');
const ROOTS = ['src/app', 'vendor/ui-kit/src', 'vendor/ui-kit/shell', 'vendor/ui-kit/pwa'];

function files(dir: string): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return [];
  }
  return entries.flatMap((name) => {
    if (name === 'node_modules') return [];
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    if (name.endsWith('.spec.ts')) return [];
    return name.endsWith('.html') || name.endsWith('.ts') ? [path] : [];
  });
}

const TEMPLATE = /\(scroll\)\s*=/;
const HOST = /['"`]\((?:window:|document:)?scroll\)['"`]\s*:|@HostListener\(\s*['"`](?:window:|document:)?scroll['"`]/;

describe('scrollListenersContract', () => {
  it('binds no scroll event through Angular', () => {
    const found = ROOTS.flatMap((root) => files(join(FRONTEND, root))).filter((path) => {
      const text = readFileSync(path, 'utf8');
      return TEMPLATE.test(text) || HOST.test(text);
    });
    expect(found.map((p) => relative(FRONTEND, p))).toEqual([]);
  });
});
