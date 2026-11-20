/**
 * Error text contract of the app templates (spec 001963). An error text in a dialog, a sheet
 * or a form is an `app-error-text` of the kit. This spec reads the HTML and fails on an error
 * paragraph that a template writes itself.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..');

function htmlFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return htmlFiles(path);
    return name.endsWith('.html') ? [path] : [];
  });
}

/** The line of each hand-written error text of `source`: a `<p>` alert with an error class. */
export function handErrors(source: string): readonly number[] {
  return Array.from(
    source.matchAll(/<p\b(?=[^>]*\brole="alert")(?=[^>]*\bclass="[^"]*__(?:error|refusal)\b)[^>]*>/g),
    (m) => source.slice(0, m.index).split('\n').length,
  );
}

describe('ErrorTextTemplates', () => {
  it('finds an error paragraph with an alert role and passes other alerts', () => {
    expect(handErrors('<div>\n<p class="x__error" role="alert">{{ e }}</p>')).toEqual([2]);
    expect(handErrors('<p role="alert" class="y__refusal">{{ e }}</p>')).toEqual([1]);
    expect(handErrors('<p class="x__error">{{ e }}</p>')).toEqual([]);
    expect(handErrors('<p class="x__status" role="alert">{{ e }}</p>')).toEqual([]);
    expect(handErrors('<app-error-text>{{ e }}</app-error-text>')).toEqual([]);
  });

  it('leaves every error text to app-error-text (001963)', () => {
    const offenders = htmlFiles(join(SRC, 'app')).flatMap((path) =>
      handErrors(readFileSync(path, 'utf8')).map((line) => `${relative(SRC, path)}:${line}`),
    );
    expect(offenders).toEqual([]);
  });
});
