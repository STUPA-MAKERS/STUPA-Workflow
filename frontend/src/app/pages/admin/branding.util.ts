/**
 * Branding-Validierung (T-34 / #21). Footer- und Rechts-Links dürfen nur sichere
 * Schemata tragen — `http(s):` und `mailto:`. Andere (v.a. `javascript:`, `data:`)
 * werden **clientseitig abgelehnt**, da die URLs als `branding`-JSON site-weit
 * persistiert und in Header/Footer als Links gerendert werden (gespeicherter
 * XSS-Vektor sonst). Server validiert autoritativ; das ist Sofort-Feedback.
 */
import type { Branding } from './admin.models';

export const ALLOWED_LINK_SCHEMES: readonly string[] = ['http:', 'https:', 'mailto:'] as const;

/** true, wenn `url` ein nicht-leerer Link mit erlaubtem Schema ist. */
export function isAllowedLinkUrl(url: string | null | undefined): boolean {
  const u = (url ?? '').trim();
  if (!u) return false;
  try {
    return ALLOWED_LINK_SCHEMES.includes(new URL(u).protocol);
  } catch {
    return false; // relativ/ungültig → ablehnen
  }
}

/** Alle unzulässigen Link-URLs eines Branding-Entwurfs (Footer + Rechts-Links). */
export function brandingLinkErrors(branding: Branding | null | undefined): string[] {
  if (!branding) return [];
  const urls: string[] = [
    ...branding.footerColumns.flatMap((c) => c.links.map((l) => l.url)),
    ...branding.legalLinks.map((l) => l.url),
  ];
  return urls.filter((u) => !isAllowedLinkUrl(u));
}
