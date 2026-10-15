import { CD_SQUARE_LOGO_ACCEPT, SQUARE_LOGO_MIN_PX, SQUARE_LOGO_TOLERANCE } from '../admin.models';

/** The pixel size of an image. */
export interface ImageSize {
  width: number;
  height: number;
}

/**
 * The client-side verdict on a square logo. The server checks the same rules from the
 * header of the file (`check_square_logo`), so this is a preview only.
 */
export type SquareVerdict = 'ok' | 'notSquare' | 'tooSmall';

/** Square within the tolerance first, then large enough: the order of the server checks. */
export function squareVerdict(size: ImageSize): SquareVerdict {
  const { width, height } = size;
  if (Math.abs(width - height) > SQUARE_LOGO_TOLERANCE * Math.max(width, height)) {
    return 'notSquare';
  }
  if (Math.min(width, height) < SQUARE_LOGO_MIN_PX) return 'tooSmall';
  return 'ok';
}

/**
 * The letters of the placeholder of a variant without a square logo: the first letters of
 * the first and the last word, or the first two letters of a single word ("STUPA" gives
 * "ST", "HSRT INF" gives "HI").
 */
export function variantInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter((w) => w.length > 0);
  if (words.length === 0) return '?';
  const letters =
    words.length === 1 ? [...words[0]].slice(0, 2).join('') : [...words[0]][0] + [...words[words.length - 1]][0];
  return letters.toLocaleUpperCase();
}

/** True for a type that the square slot takes (PNG, JPEG, WebP). */
export function isSquareLogoType(file: File): boolean {
  return CD_SQUARE_LOGO_ACCEPT.split(',').includes(file.type);
}

/**
 * Load an image URL (an object URL of the picked file) and read its natural size.
 *
 * @param url The URL to load.
 * @param make Builds the image element. Tests pass a fake, because jsdom never loads one.
 */
export function readImageSize(
  url: string,
  make: () => HTMLImageElement = () => new Image(),
): Promise<ImageSize> {
  return new Promise((resolve, reject) => {
    const img = make();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => reject(new Error('image could not be read'));
    img.src = url;
  });
}
