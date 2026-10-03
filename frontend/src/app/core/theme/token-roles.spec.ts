/**
 * Each accent token has one role. The check is on the source, so a wrong use fails at
 * review time and not on the projector.
 *
 * - `--color-accent` is the FILL (#72a384 in both themes). As text it has less than 3:1
 *   on the light surfaces. Text uses `--color-accent-text`.
 * - `--color-primary` and `--color-success` are the accent as TEXT (#3c6a4d light). As a
 *   box background they paint a second, darker green beside the accent fills. A fill uses
 *   `--color-accent`.
 *
 * SVG `fill` is not checked: a small graphic needs 3:1 against its surface, and the text
 * tokens give it that.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';

const FRONTEND = join(__dirname, '..', '..', '..', '..');
const ROOTS = [join(FRONTEND, 'src'), join(FRONTEND, 'vendor', 'ui-kit', 'src')];

/** `color: var(--color-accent)`, but not `border-color`, `accent-color` and the like. */
const ACCENT_AS_TEXT = /(?<![-\w])color\s*:\s*var\(--color-accent\)/;

/** A box filled with a text token. */
const TEXT_AS_FILL = /background(?:-color)?\s*:\s*var\(--color-(?:primary|success)\)/;

function stylesheets(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...stylesheets(full));
    else if (extname(entry) === '.scss' || extname(entry) === '.css') out.push(full);
  }
  return out;
}

function offenders(pattern: RegExp): string[] {
  const out: string[] = [];
  for (const file of ROOTS.flatMap(stylesheets)) {
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, i) => {
        if (pattern.test(line)) out.push(`${relative(FRONTEND, file)}:${i + 1}`);
      });
  }
  return out;
}

describe('accent token roles', () => {
  it('scans the stylesheets of the app and the ui-kit', () => {
    expect(ROOTS.flatMap(stylesheets).length).toBeGreaterThan(50);
  });

  it('never uses the accent fill as a text colour', () => {
    expect(offenders(ACCENT_AS_TEXT)).toEqual([]);
  });

  it('never fills a box with an accent text token', () => {
    expect(offenders(TEXT_AS_FILL)).toEqual([]);
  });
});
