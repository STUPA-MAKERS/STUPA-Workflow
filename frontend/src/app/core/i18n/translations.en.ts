import enCatalog from './catalog/en.json';
import type { TranslationKey } from './translations';

/**
 * The EN catalog (`catalog/en.json`). A missing key falls back to DE at runtime.
 *
 * It is a module of its own because the build then puts it in a lazy chunk: about half
 * of the strings of the app, which a German reader never needs. `loadCatalog` imports it
 * before the first paint when the active locale is EN.
 */
export const en: Partial<Record<TranslationKey, string>> = enCatalog;
