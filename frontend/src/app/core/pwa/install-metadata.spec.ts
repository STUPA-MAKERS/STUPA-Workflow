/**
 * The install metadata must hold for Android and Chrome, and for iOS, which reads
 * other sources.
 *
 * iOS does not read the icons of the manifest. "Add to Home Screen" takes the
 * `apple-touch-icon` of index.html and fills a transparent area with black, so that
 * icon must be an opaque PNG. Chrome offers the install only with a 192 px and a 512 px
 * icon in the manifest.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

/** The project root is four levels up from src/app/core/pwa. */
const ROOT = join(__dirname, '..', '..', '..', '..');
const PUBLIC = join(ROOT, 'public');

interface ManifestIcon {
  src: string;
  sizes: string;
  purpose: string;
}

function indexHtml(): string {
  return readFileSync(join(ROOT, 'src', 'index.html'), 'utf8');
}

interface Manifest {
  id: string;
  display: string;
  icons: ManifestIcon[];
  shortcuts: { name: string; url: string; icons: Omit<ManifestIcon, 'purpose'>[] }[];
  launch_handler: { client_mode: string[] };
}

function manifest(): Manifest {
  return JSON.parse(readFileSync(join(PUBLIC, 'manifest.webmanifest'), 'utf8'));
}

/** Width, height and alpha of a PNG, read from its IHDR chunk. */
function png(path: string): { width: number; height: number; alpha: boolean } {
  const bytes = readFileSync(path);
  const colourType = bytes[25];
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
    alpha: colourType === 4 || colourType === 6,
  };
}

describe('install metadata', () => {
  it('gives iOS an opaque 180 px home screen icon', () => {
    const href = /<link rel="apple-touch-icon" sizes="180x180" href="([^"]+)"/.exec(
      indexHtml(),
    )?.[1];
    expect(href).toBeDefined();
    expect(png(join(PUBLIC, href as string))).toEqual({ width: 180, height: 180, alpha: false });
  });

  /**
   * iOS takes the image only when it is exactly as large as the screen. The sizes go from the
   * iPhone SE (375 x 667) to the 16 Pro Max and 17 Pro Max (440 x 956).
   */
  it('gives every iPhone screen a launch image in the light and the dark theme', () => {
    const links = [
      ...indexHtml().matchAll(/<link rel="apple-touch-startup-image" media="([^"]+)" href="([^"]+)"/g),
    ];
    const screens = new Map<string, Set<string>>();
    for (const [, media, href] of links) {
      const w = Number(/\(device-width: (\d+)px\)/.exec(media)?.[1]);
      const h = Number(/\(device-height: (\d+)px\)/.exec(media)?.[1]);
      const ratio = Number(/\(-webkit-device-pixel-ratio: (\d)\)/.exec(media)?.[1]);
      const scheme = /\(prefers-color-scheme: (light|dark)\)/.exec(media)?.[1] as string;
      expect(media).toContain('(orientation: portrait)');
      expect(png(join(PUBLIC, href))).toEqual({ width: w * ratio, height: h * ratio, alpha: false });
      const key = `${w}x${h}@${ratio}`;
      screens.set(key, (screens.get(key) ?? new Set()).add(scheme));
    }
    expect(screens.has('375x667@2')).toBe(true);
    expect(screens.has('440x956@3')).toBe(true);
    for (const schemes of screens.values()) expect([...schemes].sort()).toEqual(['dark', 'light']);
  });

  /**
   * WCAG 1.4.4 requires that the person can zoom. The inputs are 16 px, so iOS does not zoom on
   * focus.
   */
  it('keeps pinch zoom and lets the on-screen keyboard resize the layout', () => {
    const content = /<meta\s+name="viewport"\s+content="([^"]+)"/.exec(indexHtml())?.[1] ?? '';
    expect(content).not.toMatch(/user-scalable=no|maximum-scale/);
    expect(content).toContain('viewport-fit=cover');
    expect(content).toContain('interactive-widget=resizes-content');
  });

  it('marks the page as a standalone app for iOS', () => {
    expect(indexHtml()).toContain('<meta name="apple-mobile-web-app-capable" content="yes" />');
  });

  it('gives every manifest icon an opaque file of its declared size', () => {
    for (const icon of manifest().icons) {
      const [width, height] = icon.sizes.split('x').map(Number);
      expect(existsSync(join(PUBLIC, icon.src))).toBe(true);
      expect(png(join(PUBLIC, icon.src))).toEqual({ width, height, alpha: false });
    }
  });

  it('offers the shortcuts of a long press on the app icon, on routes of the app', () => {
    const m = manifest();
    const routes = readFileSync(join(ROOT, 'src', 'app', 'app.routes.ts'), 'utf8');
    expect(m.shortcuts.map((s) => [s.name, s.url])).toEqual([
      ['Neuer Antrag', 'apply'],
      ['Meine To-Dos', 'todos'],
      ['Sitzungen', 'meetings'],
    ]);
    for (const shortcut of m.shortcuts) {
      expect(routes).toContain(`path: '${shortcut.url}',`);
      for (const icon of shortcut.icons) {
        const [width, height] = icon.sizes.split('x').map(Number);
        expect(png(join(PUBLIC, icon.src))).toEqual({ width, height, alpha: false });
      }
    }
  });

  it('opens a link in the running app, not in a second window', () => {
    expect(manifest().launch_handler).toEqual({ client_mode: ['navigate-existing', 'auto'] });
  });

  it('declares the icons and the display mode that Chrome needs for the install', () => {
    const m = manifest();
    const sizes = m.icons.filter((i) => i.purpose === 'any').map((i) => i.sizes);
    expect(sizes).toEqual(expect.arrayContaining(['192x192', '512x512']));
    expect(m.display).toBe('standalone');
    expect(m.id).toBe('/');
  });
});
