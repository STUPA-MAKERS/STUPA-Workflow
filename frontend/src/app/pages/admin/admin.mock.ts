/**
 * Mock-Seed-Daten für den Admin-Bereich (T-34). Nur aktiv, solange T-24
 * (admin-API) + #21 (site-config) nicht real gemergt sind (`USE_MOCK_API`).
 * Beim Backend-Merge entfällt diese Datei zusammen mit den Mock-Zweigen im
 * `AdminApiService`.
 */
import type {
  AdminPrincipal,
  Branding,
  FormOverviewItem,
  Gremium,
  NotificationRule,
  Role,
  WebhookConfig,
} from './admin.models';

/** Permission-Katalog (Spiegel von `app.shared.permissions.PERMISSION_CATALOGUE`). */
export const MOCK_PERMISSIONS: string[] = [
  'application.read',
  'application.create',
  'application.update',
  'application.transition',
  'application.manage',
  'form.configure',
  'flow.configure',
  'vote.manage',
  'vote.cast',
  'meeting.manage',
  'protocol.manage',
  'protocol.write',
  'budget.manage',
  'budget.view',
  'notification.manage',
  'webhook.manage',
  'audit.read',
  'admin.config',
  'admin.roles',
];

export const MOCK_PRINCIPALS: AdminPrincipal[] = [
  {
    id: 'p-1',
    sub: 'kc|alex.admin',
    email: 'alex@stupa.example',
    displayName: 'Alex Admin',
    lastLogin: '2026-06-06T18:20:00+00:00',
    assignments: [
      {
        id: 'a-1',
        principalId: 'p-1',
        roleId: 'r-admin',
        gremiumId: null,
        grantedBy: 'bootstrap',
        validFrom: null,
        validUntil: null,
        delegateVoting: false,
      },
    ],
  },
  {
    id: 'p-2',
    sub: 'kc|robin.member',
    email: 'robin@stupa.example',
    displayName: 'Robin Mitglied',
    lastLogin: '2026-06-05T09:00:00+00:00',
    assignments: [
      {
        id: 'a-2',
        principalId: 'p-2',
        roleId: 'r-member',
        gremiumId: null,
        grantedBy: 'kc|alex.admin',
        validFrom: null,
        validUntil: null,
        delegateVoting: false,
      },
    ],
  },
  {
    id: 'p-3',
    sub: 'kc|sam.neu',
    email: 'sam@stupa.example',
    displayName: 'Sam Neu',
    lastLogin: null,
    assignments: [],
  },
];

export const MOCK_GREMIEN: Gremium[] = [
  { id: 'g-stupa', name: 'Studierendenparlament', slug: 'stupa', cdVariant: 'stupa', defaultLang: 'de', allowVoteDelegation: true },
  { id: 'g-asta', name: 'AStA', slug: 'asta', cdVariant: 'asta', defaultLang: 'de', allowVoteDelegation: false },
];

/**
 * Fallback-Rollenliste für den Options-Provider (#77), solange die echte
 * `/admin/roles` (T-24) leer/abwesend ist. Spiegelt die seed-Rollen aus
 * `auth/seed` (member/referent/vorstand/admin). TODO(T-24): durch die echte
 * Rollenliste ersetzen — der Options-Provider bevorzugt API-Daten automatisch.
 */
export const MOCK_ROLES: Role[] = [
  { id: 'r-member', key: 'member', label: { de: 'Mitglied', en: 'Member' }, permissions: ['application.read', 'vote.cast'] },
  { id: 'r-referent', key: 'referent', label: { de: 'Referent:in', en: 'Officer' }, permissions: ['application.read', 'application.update', 'application.transition', 'vote.manage'] },
  { id: 'r-vorstand', key: 'vorstand', label: { de: 'Vorstand', en: 'Board' }, permissions: ['application.read', 'budget.view', 'meeting.manage'] },
  { id: 'r-admin', key: 'admin', label: { de: 'Administration', en: 'Administration' }, permissions: [...MOCK_PERMISSIONS] },
];

/** Seed für den Formular-Überblick (#75), bis `/admin/application-types` real ist. */
export const MOCK_FORMS: FormOverviewItem[] = [
  { id: 'f-foerderung', name: { de: 'Förderantrag', en: 'Funding application' }, gremiumId: 'g-stupa', status: 'active', version: 3 },
  { id: 'f-veranstaltung', name: { de: 'Veranstaltungsantrag', en: 'Event application' }, gremiumId: 'g-asta', status: 'active', version: 2 },
  { id: 'f-anschaffung', name: { de: 'Anschaffungsantrag', en: 'Procurement application' }, gremiumId: 'g-stupa', status: 'draft', version: 1 },
  { id: 'f-altfall', name: { de: 'Härtefallantrag', en: 'Hardship application' }, gremiumId: 'g-asta', status: 'inactive', version: 5 },
];

export const MOCK_WEBHOOKS: WebhookConfig[] = [
  {
    id: 'wh-1',
    name: 'Matrix-Bridge',
    url: 'https://hooks.example.org/matrix',
    events: ['application_created', 'status_changed'],
    active: true,
  },
];

export const MOCK_NOTIFICATION_RULES: NotificationRule[] = [
  {
    id: 'nr-1',
    event: 'status_changed',
    recipients: [{ kind: 'applicant' }],
    templateKey: 'status_changed_applicant',
    enabled: true,
  },
];

export const MOCK_BRANDING: Branding = {
  logos: {},
  footerColumns: [
    {
      label: { de: 'Über uns', en: 'About' },
      links: [{ label: { de: 'Impressum', en: 'Imprint' }, url: 'https://example.org/impressum' }],
    },
  ],
  copyright: { de: '© Studierendenschaft', en: '© Student body' },
  legalLinks: [
    { label: { de: 'Impressum', en: 'Imprint' }, url: 'https://example.org/impressum' },
    { label: { de: 'Datenschutz', en: 'Privacy' }, url: 'https://example.org/privacy' },
  ],
  freetexts: {
    loginHint: { de: 'Mit Hochschul-Account anmelden.', en: 'Sign in with your university account.' },
    welcome: { de: 'Willkommen auf der Antragsplattform.', en: 'Welcome to the application platform.' },
    support: { de: 'Bei Fragen: support@example.org', en: 'Questions? support@example.org' },
    emailFooter: { de: 'Automatische Nachricht – nicht antworten.', en: 'Automated message – do not reply.' },
  },
};
