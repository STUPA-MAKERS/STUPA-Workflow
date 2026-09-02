import { isApplePlatform, searchShortcutLabel } from './shortcut';

/**
 * The trigger shipped showing `⌘K` unconditionally. This platform runs in a university,
 * where nearly nobody is on a Mac, so it named a key most readers do not have. These
 * pin the detection and the wording.
 */
describe('search shortcut', () => {
  const nav = (platform: string, uaPlatform?: string): Navigator =>
    ({ platform, ...(uaPlatform ? { userAgentData: { platform: uaPlatform } } : {}) }) as Navigator;

  it.each([
    ['MacIntel', true],
    ['iPhone', true],
    ['iPad', true],
    ['Win32', false],
    ['Linux x86_64', false],
    ['', false],
  ])('recognises %s as Apple hardware: %s', (platform, expected) => {
    expect(isApplePlatform(nav(platform))).toBe(expected);
  });

  it('prefers userAgentData when the browser provides it', () => {
    // `navigator.platform` is deprecated; a browser that offers the newer hint should win.
    expect(isApplePlatform(nav('Win32', 'macOS'))).toBe(true);
    expect(isApplePlatform(nav('MacIntel', 'Windows'))).toBe(false);
  });

  it('spells the shortcut for the platform, in the reader\'s language', () => {
    expect(searchShortcutLabel('de', nav('MacIntel'))).toBe('⌘K');
    expect(searchShortcutLabel('en', nav('MacIntel'))).toBe('⌘K');
    expect(searchShortcutLabel('de', nav('Win32'))).toBe('Strg+K');
    expect(searchShortcutLabel('en', nav('Win32'))).toBe('Ctrl+K');
  });
});
