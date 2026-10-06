import type { TranslationKey } from '@core/i18n/translations';

/** A section of the permission list of a global role. */
export interface PermissionSection {
  key: 'applications' | 'budget' | 'meetings' | 'admin' | 'security' | 'other';
  title: TranslationKey;
  /** The permission keys of the section, in the order of the catalogue. */
  keys: string[];
}

/** The sections in display order, each with the key prefixes it takes. */
const SECTIONS: readonly { key: PermissionSection['key']; title: TranslationKey; prefixes: readonly string[] }[] = [
  { key: 'applications', title: 'admin.roles.section.applications', prefixes: ['application.'] },
  { key: 'budget', title: 'admin.roles.section.budget', prefixes: ['budget.'] },
  { key: 'meetings', title: 'admin.roles.section.meetings', prefixes: ['meeting.', 'vote.', 'protocol.', 'session.'] },
  { key: 'admin', title: 'admin.roles.section.admin', prefixes: ['admin.', 'form.', 'flow.', 'webhook.'] },
  { key: 'security', title: 'admin.roles.section.security', prefixes: ['audit.', 'privacy.', 'backup.', 'mcp.'] },
];

/**
 * Put the permission catalogue of the API (`GET /admin/permissions`) into sections.
 *
 * The keys come from the API only: a key the server removed never shows, and a key it
 * adds shows without a frontend change. The prefix of a key picks its section. A key
 * with an unknown prefix goes into "Weitere", so no key is ever lost. Empty sections
 * are left out.
 */
export function permissionSections(catalogue: readonly string[]): PermissionSection[] {
  const out: PermissionSection[] = SECTIONS.map((s) => ({ key: s.key, title: s.title, keys: [] }));
  const other: PermissionSection = { key: 'other', title: 'admin.roles.section.other', keys: [] };
  for (const perm of catalogue) {
    const index = SECTIONS.findIndex((s) => s.prefixes.some((p) => perm.startsWith(p)));
    (index >= 0 ? out[index] : other).keys.push(perm);
  }
  return [...out, other].filter((s) => s.keys.length > 0);
}
