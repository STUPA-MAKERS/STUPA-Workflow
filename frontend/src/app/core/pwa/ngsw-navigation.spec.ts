/**
 * The service worker must not answer for paths the server renders itself.
 *
 * `navigationUrls` claims `/**`, so without an exclusion the worker serves the Angular
 * shell for a server path and the router turns it into the app's own 404 page.
 *
 * The check is on the config rather than on a running worker, because that is where the
 * mistake is made and it holds without a build.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

interface NgswConfig {
  navigationUrls: string[];
}

/** Paths the SERVER answers with its own HTML. None may reach the Angular router. */
const SERVER_RENDERED = ['/api/**', '/.well-known/**'];

/** The project root is four levels up from src/app/core/pwa. */
function config(): NgswConfig {
  const path = join(__dirname, '..', '..', '..', '..', 'ngsw-config.json');
  return JSON.parse(readFileSync(path, 'utf8')) as NgswConfig;
}

describe('service worker navigation URLs', () => {
  it.each(SERVER_RENDERED)('leaves %s to the server', (pattern) => {
    expect(config().navigationUrls).toContain(`!${pattern}`);
  });

  it('still claims everything else, so a deep link into the app works offline', () => {
    expect(config().navigationUrls).toContain('/**');
  });
});
