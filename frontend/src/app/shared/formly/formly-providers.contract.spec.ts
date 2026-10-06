import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Formly is not provided at the root (it would be part of the initial bundle). So every
 * component whose template has a `<formly-form>` must provide `provideFormly()` itself;
 * without it the field types are unknown and the form fails at runtime.
 */
const app = join(__dirname, '../..');

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe('Formly providers', () => {
  const templates = files(app).filter((f) => f.endsWith('.component.html'));
  const withForm = templates.filter((f) => readFileSync(f, 'utf8').includes('<formly-form'));

  it('finds the components with a Formly form', () => {
    expect(withForm.length).toBeGreaterThanOrEqual(4);
  });

  it.each(withForm.map((f) => [f.slice(app.length + 1)]))('%s provides provideFormly()', (rel) => {
    const ts = readFileSync(join(app, rel.replace(/\.html$/, '.ts')), 'utf8');
    expect(ts).toMatch(/providers:\s*\[[^\]]*provideFormly\(\)/s);
  });

  it('is not provided at the root', () => {
    expect(readFileSync(join(app, 'app.config.ts'), 'utf8')).not.toContain('provideFormly');
  });
});
