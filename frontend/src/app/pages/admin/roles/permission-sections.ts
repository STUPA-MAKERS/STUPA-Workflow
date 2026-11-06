import type { TranslationKey } from '@core/i18n/translations';

/** A section of the permission list of a global role. */
export interface PermissionSection {
  readonly key: 'applications' | 'budget' | 'meetings' | 'admin' | 'security' | 'other';
  readonly title: TranslationKey;
  /** The permission keys of the section, in the order of the catalogue. */
  readonly keys: readonly string[];
}

/** The sections in display order, each with the key prefixes it takes. */
const SECTIONS: readonly {
  readonly key: PermissionSection['key'];
  readonly title: TranslationKey;
  readonly prefixes: readonly string[];
}[] = [
  { key: 'applications', title: 'admin.roles.section.applications', prefixes: ['application.'] },
  { key: 'budget', title: 'admin.roles.section.budget', prefixes: ['budget.'] },
  {
    key: 'meetings',
    title: 'admin.roles.section.meetings',
    prefixes: ['meeting.', 'gremium.', 'vote.', 'protocol.', 'session.'],
  },
  {
    key: 'admin',
    title: 'admin.roles.section.admin',
    prefixes: ['admin.', 'form.', 'flow.', 'webhook.', 'ticket.'],
  },
  {
    key: 'security',
    title: 'admin.roles.section.security',
    prefixes: ['audit.', 'privacy.', 'backup.', 'mcp.'],
  },
];

/**
 * Put the permission catalogue of the API (`GET /admin/permissions`) into sections.
 *
 * The keys come from the API only: a key the server removed never shows, and a key it
 * adds shows without a frontend change. The prefix of a key picks its section. A key
 * with an unknown prefix goes into "Weitere", so no key is ever lost. Empty sections
 * are left out.
 */
export function permissionSections(catalogue: readonly string[]): readonly PermissionSection[] {
  const sectionOf = (perm: string): number =>
    SECTIONS.findIndex((s) => s.prefixes.some((p) => perm.startsWith(p)));
  const known = SECTIONS.map((s, index) => ({
    key: s.key,
    title: s.title,
    keys: catalogue.filter((perm) => sectionOf(perm) === index),
  }));
  const other: PermissionSection = {
    key: 'other',
    title: 'admin.roles.section.other',
    keys: catalogue.filter((perm) => sectionOf(perm) < 0),
  };
  return [...known, other].filter((s) => s.keys.length > 0);
}
