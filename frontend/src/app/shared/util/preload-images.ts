import { InjectionToken } from '@angular/core';

/** The longest wait for the images of a list before it shows (spec 001280). */
export const IMAGE_PRELOAD_LIMIT_MS = 3000;

/** Loads a set of image URLs; resolves when each one has loaded or failed. */
export type ImagePreloader = (urls: readonly string[]) => Promise<void>;

/**
 * Load the images of a list into the browser cache, so the rows show with their images at
 * once instead of one image after the other.
 *
 * The promise never rejects: an image that fails counts as done, because its row shows its
 * fallback. After `limitMs` it resolves anyway, because one slow image must not hold the
 * whole list.
 *
 * @param urls The image URLs. Duplicates and empty strings are skipped.
 * @param limitMs The longest wait in milliseconds.
 * @param make Builds the image element. Tests pass a fake, because jsdom never loads one.
 */
export function preloadImages(
  urls: readonly string[],
  limitMs = IMAGE_PRELOAD_LIMIT_MS,
  make: () => HTMLImageElement = () => new Image(),
): Promise<void> {
  const unique = [...new Set(urls.filter((u) => !!u))];
  if (!unique.length) return Promise.resolve();
  const each = unique.map(
    (url) =>
      new Promise<void>((resolve) => {
        const img = make();
        img.onload = () => resolve();
        img.onerror = () => resolve();
        img.src = url;
      }),
  );
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, limitMs);
    void Promise.all(each).then(() => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/** The preloader of the app. A spec replaces it, because jsdom never loads an image. */
export const IMAGE_PRELOADER = new InjectionToken<ImagePreloader>('IMAGE_PRELOADER', {
  providedIn: 'root',
  factory: () => (urls) => preloadImages(urls),
});
