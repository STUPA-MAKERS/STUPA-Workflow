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
    return false;
  }
}

/** All disallowed URLs of the legal links of a branding draft. */
export function brandingLinkErrors(branding: Branding | null | undefined): string[] {
  if (!branding) return [];
  return branding.legalLinks.map((l) => l.url).filter((u) => !isAllowedLinkUrl(u));
}
