/**
 * How to spell the search shortcut for the platform the reader is on.
 *
 * The trigger showed `⌘K` unconditionally, which is wrong for everyone not on a Mac —
 * and this platform runs in a university, where that is nearly everyone. A hint that
 * names a key the keyboard does not have is worse than no hint.
 */
export function isApplePlatform(nav: Navigator = navigator): boolean {
  // `navigator.platform` is deprecated but still the most reliable signal, and
  // `userAgentData` is Chromium-only. Read both and accept either.
  const data = (nav as Navigator & { userAgentData?: { platform?: string } }).userAgentData;
  const hint = data?.platform ?? nav.platform ?? '';
  return /mac|iphone|ipad|ipod/i.test(hint);
}

/** `⌘K` on Apple hardware, `Strg+K` everywhere else — in the reader's own language. */
export function searchShortcutLabel(locale: string, nav: Navigator = navigator): string {
  if (isApplePlatform(nav)) return '⌘K';
  return locale === 'de' ? 'Strg+K' : 'Ctrl+K';
}
