/**
 * Branding validation. Footer links and legal links may carry safe schemes only: `http:`,
 * `https:` and `mailto:`. The client rejects every other scheme, above all `javascript:` and
 * `data:`. The platform stores these URLs site-wide as `branding` JSON and renders them as
 * links in the header and the footer. An unsafe scheme is a stored XSS vector. The server
 * holds the authoritative check. This one only gives instant feedback.
 */
import type { Branding } from './admin.models';

const ALLOWED_LINK_SCHEMES: readonly string[] = ['http:', 'https:', 'mailto:'] as const;

/** true when `url` is a non-empty link with an allowed scheme. */
export function isAllowedLinkUrl(url: string | null | undefined): boolean {
  const u = (url ?? '').trim();
  if (!u) return false;
  try {
    return ALLOWED_LINK_SCHEMES.includes(new URL(u).protocol);
  } catch {
    return false; // a relative or invalid URL lands here and is rejected
  }
}

/** All disallowed link URLs of a branding draft: the footer links and the legal links. */
export function brandingLinkErrors(branding: Branding | null | undefined): string[] {
  if (!branding) return [];
  const urls: string[] = [
    ...branding.footerColumns.flatMap((c) => c.links.map((l) => l.url)),
    ...branding.legalLinks.map((l) => l.url),
  ];
  return urls.filter((u) => !isAllowedLinkUrl(u));
}
