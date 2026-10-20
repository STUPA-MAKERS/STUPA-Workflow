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

// Four levels up from src/app/core/pwa to the project root.
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

function manifest(): { id: string; display: string; icons: ManifestIcon[] } {
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

  it('keeps pinch zoom and lets the on-screen keyboard resize the layout', () => {
    const content = /<meta\s+name="viewport"\s+content="([^"]+)"/.exec(indexHtml())?.[1] ?? '';
    // WCAG 1.4.4: the person can zoom. The inputs are 16 px, so iOS does not zoom on focus.
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

  it('declares the icons and the display mode that Chrome needs for the install', () => {
    const m = manifest();
    const sizes = m.icons.filter((i) => i.purpose === 'any').map((i) => i.sizes);
    expect(sizes).toEqual(expect.arrayContaining(['192x192', '512x512']));
    expect(m.display).toBe('standalone');
    expect(m.id).toBe('/');
  });
});
