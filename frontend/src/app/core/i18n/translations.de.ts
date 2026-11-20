import deCatalog from './catalog/de.json';
import type { TranslationKey } from './translations';

/**
 * The DE catalog (`catalog/de.json`), the reference and the fallback of every locale.
 *
 * It is a module of its own because the build then puts it in a lazy chunk of its own
 * (spec 002003): the main bundle stays a quarter smaller, and a release that changes no text
 * keeps the chunk in the cache of the browser. `main.ts` starts the load before the app
 * boots, and the app initializer waits for it, so the first paint has the texts.
 */
export const deTable: Record<TranslationKey, string> = deCatalog;
