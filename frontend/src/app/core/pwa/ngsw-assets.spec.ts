/**
 * The service worker must not hash a file that the server generates at runtime.
 *
 * This exists because it did. `/manifest.webmanifest` was in the prefetch group, but
 * nginx answers it from the API with the active site config. The worker checks each
 * hashed file against the hash of the build. The hash never matched, so every new version
 * failed to install (`VERSION_INSTALLATION_FAILED`), no update prompt came, and a reload
 * kept the old version from the cache.
 *
 * The check is on the config rather than on a running worker, because that is where the
 * mistake is made and it holds without a build.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

interface AssetGroup {
  name: string;
  resources: { files?: string[]; urls?: string[] };
}

interface NgswConfig {
  assetGroups: AssetGroup[];
}

/** Paths that nginx answers from the API, not from the build output. */
const SERVER_GENERATED = ['/manifest.webmanifest'];

function config(): NgswConfig {
  // Four levels up from src/app/core/pwa to the project root.
  const path = join(__dirname, '..', '..', '..', '..', 'ngsw-config.json');
  return JSON.parse(readFileSync(path, 'utf8')) as NgswConfig;
}

/** A small glob match for the patterns of ngsw-config: `**`, `*` and `(a|b)`. */
function matches(pattern: string, path: string): boolean {
  const source = pattern
    .replace(/[.+^${}[\]\\]/g, '\\$&')
    .replace(/\*\*\//g, 'GLOBSTAR')
    .replace(/\*\*/g, '.*')
    .replace(/\*/g, '[^/]*')
    .replace(/GLOBSTAR/g, '(?:.*/)?');
  return new RegExp(`^${source}$`).test(path);
}

describe('service worker asset groups', () => {
  it.each(SERVER_GENERATED)('do not hash %s', (path) => {
    for (const group of config().assetGroups) {
      const patterns = [...(group.resources.files ?? []), ...(group.resources.urls ?? [])];
      expect(patterns.filter((p) => matches(p, path))).toEqual([]);
    }
  });

  it('still prefetch the app shell', () => {
    const app = config().assetGroups.find((g) => g.name === 'app');
    expect(app?.resources.files).toEqual(expect.arrayContaining(['/index.html', '/*.js']));
  });

  it('match a pattern the way the worker does', () => {
    expect(matches('/*.js', '/main-abc.js')).toBe(true);
    expect(matches('/*.js', '/a/main.js')).toBe(false);
    expect(matches('/**/*.(svg|png)', '/icons/a.png')).toBe(true);
    expect(matches('/**/*.(svg|png)', '/a.svg')).toBe(true);
    expect(matches('/manifest.webmanifest', '/manifest.webmanifest')).toBe(true);
  });
});
