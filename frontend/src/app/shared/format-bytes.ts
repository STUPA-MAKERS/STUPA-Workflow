/**
 * The one formatter for file sizes. Every size goes through `Intl.NumberFormat` in the
 * format locale, so German shows "1,5 MB" and English "1.5 MB". The base is binary.
 *
 * Three styles cover the pages:
 * - `file`: whole KB below one MB ("212 KB"), else MB with at most one decimal
 *   ("1,5 MB", "50 MB"). A few bytes read "1 KB", never "0 KB". For uploads.
 * - `storage`: B up to TB, one decimal below 10, else whole numbers ("413 MB", "4,2 GB").
 *   For archives and status lines.
 * - `fixed`: B up to TB, always one decimal from KB up ("1,0 KB", "2,5 MB"). For the
 *   attachment list.
 *
 * An invalid size (negative, NaN, infinite, null) gives "—".
 */
export type ByteStyle = 'file' | 'storage' | 'fixed';

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const;

function number(value: number, locale: string, min: number, max: number): string {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  }).format(value);
}

/** A file size for people, in the given format locale (see {@link ByteStyle}). */
export function formatBytes(
  bytes: number | null | undefined,
  locale: string,
  style: ByteStyle = 'storage',
): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '—';
  if (style === 'file') {
    const kb = bytes / 1024;
    if (kb < 1) return `${Math.ceil(kb)} KB`;
    if (kb < 1024) return `${Math.round(kb)} KB`;
    return `${number(kb / 1024, locale, 0, 1)} MB`;
  }
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return `${number(value, locale, 0, 0)} B`;
  const digits = style === 'fixed' || value < 10 ? 1 : 0;
  return `${number(value, locale, digits, digits)} ${UNITS[unit]}`;
}
