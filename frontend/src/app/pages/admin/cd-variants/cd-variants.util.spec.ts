import {
  isSquareLogoType,
  readImageSize,
  squareVerdict,
  variantInitials,
} from './cd-variants.util';

describe('cd-variants.util', () => {
  it.each([
    [{ width: 512, height: 512 }, 'ok'],
    [{ width: 1000, height: 1009 }, 'ok'], // 0.9 % off still counts as square
    [{ width: 1000, height: 980 }, 'notSquare'],
    [{ width: 300, height: 600 }, 'notSquare'],
    [{ width: 255, height: 255 }, 'tooSmall'],
    [{ width: 256, height: 256 }, 'ok'],
  ])('judges %p as %s', (size, verdict) => {
    expect(squareVerdict(size)).toBe(verdict);
  });

  it.each([
    ['image/png', true],
    ['image/jpeg', true],
    ['image/webp', true],
    ['image/svg+xml', false],
    ['application/pdf', false],
    ['', false],
  ])('takes %s for the square slot: %s', (type, ok) => {
    expect(isSquareLogoType(new File(['x'], 'f', { type }))).toBe(ok);
  });

  it.each([
    ['STUPA', 'ST'],
    ['AStA', 'AS'],
    ['HSRT INF', 'HI'],
    ['  Fachschaft  Technik Wirtschaft ', 'FW'],
    ['   ', '?'],
  ])('gives %p the initials %s', (name, letters) => {
    expect(variantInitials(name)).toBe(letters);
  });

  /** A fake image element: it loads or fails as soon as it gets a source. */
  function fakeImage(fail: boolean) {
    const img = {
      naturalWidth: 640,
      naturalHeight: 480,
      onload: null as null | (() => void),
      onerror: null as null | (() => void),
      set src(_url: string) {
        queueMicrotask(() => (fail ? img.onerror?.() : img.onload?.()));
      },
    };
    return () => img as unknown as HTMLImageElement;
  }

  it('reads the natural size of an image', async () => {
    await expect(readImageSize('blob:x', fakeImage(false))).resolves.toEqual({
      width: 640,
      height: 480,
    });
  });

  it('rejects when the image does not load', async () => {
    await expect(readImageSize('blob:x', fakeImage(true))).rejects.toThrow('image could not be read');
  });

  /** jsdom never loads the source; the call must only not throw. */
  it('builds a real image element by default', () => {
    void readImageSize('blob:x').catch(() => undefined);
  });
});
