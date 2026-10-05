/**
 * Helpers of the public apply pages.
 */

/**
 * File types the server takes (files/mime.py): PDF, images, Word, Excel, PowerPoint and
 * OpenDocument. The picker filters by it; the server sniffs the content again.
 */
export const UPLOAD_ACCEPT =
  '.pdf,.png,.jpg,.jpeg,.gif,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.ods,.odp';

/**
 * A file size for people: whole KB below one MB ("212 KB"), else MB with at most one
 * decimal in the locale ("1,5 MB", "50 MB"). Nothing is "0 KB", a few bytes "1 KB".
 */
export function formatSize(bytes: number, locale: string): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  const kb = bytes / 1024;
  // Below one KB the size rounds up, so a small file never reads as "0 KB".
  if (kb < 1) return `${Math.ceil(kb)} KB`;
  if (kb < 1024) return `${Math.round(kb)} KB`;
  const mb = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(kb / 1024);
  return `${mb} MB`;
}

/** The reference of an application: the first 8 characters of its id in upper case. */
export function shortRef(id: string | null | undefined): string {
  return (id ?? '').slice(0, 8).toUpperCase();
}
