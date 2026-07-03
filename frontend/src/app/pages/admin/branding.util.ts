/**
 * Branding validation. Footer and legal links may only carry safe schemes —
 * `http(s):` and `mailto:`. Others (notably `javascript:`, `data:`) are rejected
 * client-side, because the URLs are persisted site-wide as `branding` JSON and
 * rendered as links in header/footer (otherwise a stored XSS vector). The server
 * validates authoritatively; this is instant feedback.
 */
import type { Branding } from './admin.models';

export const ALLOWED_LINK_SCHEMES: readonly string[] = ['http:', 'https:', 'mailto:'] as const;

/** true when `url` is a non-empty link with an allowed scheme. */
export function isAllowedLinkUrl(url: string | null | undefined): boolean {
  const u = (url ?? '').trim();
  if (!u) return false;
  try {
    return ALLOWED_LINK_SCHEMES.includes(new URL(u).protocol);
  } catch {
    return false; // relative/invalid → reject
  }
}

/** All disallowed link URLs of a branding draft (footer + legal links). */
export function brandingLinkErrors(branding: Branding | null | undefined): string[] {
  if (!branding) return [];
  const urls: string[] = [
    ...branding.footerColumns.flatMap((c) => c.links.map((l) => l.url)),
    ...branding.legalLinks.map((l) => l.url),
  ];
  return urls.filter((u) => !isAllowedLinkUrl(u));
}
