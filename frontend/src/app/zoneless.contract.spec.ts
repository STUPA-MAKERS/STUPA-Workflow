/**
 * The app runs without zone.js (spec 002002). The build loads no zone polyfill, and the root
 * providers turn on the zoneless scheduler.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const FRONTEND = join(__dirname, '..', '..');
const read = (rel: string): string => readFileSync(join(FRONTEND, rel), 'utf8');

describe('zoneless contract', () => {
  it('builds without the zone.js polyfill', () => {
    const angular = JSON.parse(read('angular.json')) as {
      projects: Record<string, { architect: { build: { options: { polyfills?: string[] } } } }>;
    };
    const builds = Object.values(angular.projects).map((p) => p.architect.build.options.polyfills ?? []);
    expect(builds.flat()).not.toContain('zone.js');
  });

  it('provides the zoneless change detection at the root', () => {
    const config = read('src/app/app.config.ts');
    expect(config).toContain('provideZonelessChangeDetection()');
    expect(config).not.toContain('provideZoneChangeDetection');
  });
});
