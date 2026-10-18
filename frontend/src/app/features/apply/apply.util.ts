/**
 * Helpers of the public apply pages.
 */

import { formatBytes } from '@shared/format-bytes';

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
  return formatBytes(bytes, locale, 'file');
}

/** The reference of an application: the first 8 characters of its id in upper case. */
export function shortRef(id: string | null | undefined): string {
  return (id ?? '').slice(0, 8).toUpperCase();
}
