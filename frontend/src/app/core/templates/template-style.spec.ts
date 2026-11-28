/**
 * § S/frontend/angular/003112: a component template has no comments.
 *
 * The spec reads every `.html` file below `src/app` and fails for each one that holds `<!--`.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const APP = join(__dirname, '..', '..');

const templates: readonly string[] = (readdirSync(APP, { recursive: true }) as string[]).filter(
  (f) => f.endsWith('.html'),
);

describe('template style', () => {
  it('no comments', () => {
    const withComment = templates.filter((f) =>
      readFileSync(join(APP, f), 'utf8').includes('<!--'),
    );
    expect(withComment).toEqual([]);
  });
});
