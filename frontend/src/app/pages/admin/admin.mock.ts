/**
 * Mock seed data for the admin area. It stays active only while the admin API and the
 * site-config are not fully merged (`USE_MOCK_API`). Delete this file together with the
 * mock branches in `AdminApiService` once the backend merge lands.
 */
import type {
  AdminPrincipal,
  ApplicationTypeFull,
  Branding,
  FormDraft,
  FormOverviewItem,
  Gremium,
  Role,
  WebhookConfig,
} from './admin.models';

/** Permission catalog (mirror of `app.shared.permissions.PERMISSION_CATALOGUE`). */
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
  'budget.structure',
  'budget.book',
  'budget.view',
  'budget.export',
  'application.export',
  'webhook.manage',
  'audit.read',
  'audit.verify',
  'admin.site',
  'admin.gremien',
  'admin.types',
  'admin.types_delete',
  'admin.notifications',
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
  { id: 'g-stupa', name: 'Studierendenparlament', slug: 'stupa', cdVariantId: 'cd-stupa', defaultLang: 'de', allowVoteDelegation: true },
  { id: 'g-asta', name: 'AStA', slug: 'asta', cdVariantId: 'cd-asta', defaultLang: 'de', allowVoteDelegation: false },
];

/**
 * Fallback role list for the options provider, while the real `/admin/roles` stays
 * empty or absent. It mirrors the seed roles from `auth/seed`
 * (member/referent/vorstand/admin).
 */
export const MOCK_ROLES: Role[] = [
  { id: 'r-member', key: 'member', label: { de: 'Mitglied', en: 'Member' }, permissions: ['application.read', 'vote.cast'] },
  { id: 'r-referent', key: 'referent', label: { de: 'Referent:in', en: 'Officer' }, permissions: ['application.read', 'application.update', 'application.transition', 'vote.manage'] },
  { id: 'r-vorstand', key: 'vorstand', label: { de: 'Vorstand', en: 'Board' }, permissions: ['application.read', 'budget.view', 'meeting.manage'] },
  { id: 'r-admin', key: 'admin', label: { de: 'Administration', en: 'Administration' }, permissions: [...MOCK_PERMISSIONS] },
];

/** Seed for the forms overview, until `/admin/application-types` is real. */
export const MOCK_FORMS: FormOverviewItem[] = [
  { id: 'f-foerderung', name: { de: 'Förderantrag', en: 'Funding application' }, gremiumId: 'g-stupa', status: 'active', version: 3 },
  { id: 'f-veranstaltung', name: { de: 'Veranstaltungsantrag', en: 'Event application' }, gremiumId: 'g-asta', status: 'active', version: 2 },
  { id: 'f-anschaffung', name: { de: 'Anschaffungsantrag', en: 'Procurement application' }, gremiumId: 'g-stupa', status: 'draft', version: 1 },
  { id: 'f-altfall', name: { de: 'Härtefallantrag', en: 'Hardship application' }, gremiumId: 'g-asta', status: 'inactive', version: 5 },
];

/** Application types/forms for the forms builder — mock until the backend is real. */
export const MOCK_APP_TYPES: ApplicationTypeFull[] = [
  { id: 'f-foerderung', name: { de: 'Förderantrag', en: 'Funding application' }, gremiumId: 'g-stupa', hasBudget: true, activeFormVersionId: 'fv-foerderung-3' },
  { id: 'f-veranstaltung', name: { de: 'Veranstaltungsantrag', en: 'Event application' }, gremiumId: 'g-asta', hasBudget: false, activeFormVersionId: 'fv-veranstaltung-2' },
  { id: 'f-anschaffung', name: { de: 'Anschaffungsantrag', en: 'Procurement application' }, gremiumId: 'g-stupa', hasBudget: true, activeFormVersionId: null },
];

/** Form drafts per type — raw fields + description of the forms editor. */
export const MOCK_FORM_DRAFTS: Record<string, FormDraft> = {
  'f-foerderung': {
    applicationTypeId: 'f-foerderung',
    formVersionId: 'fv-foerderung-3',
    version: 3,
    active: true,
    description: {
      de: 'Bitte beschreibe dein Förderprojekt möglichst genau.\n\nAnträge werden im StuPa beraten.',
      en: 'Please describe your funding project as precisely as possible.',
    },
    fields: [
      { key: 'title', type: 'text', label: { de: 'Projekttitel', en: 'Project title' }, required: true },
      { key: 'amount', type: 'currency', label: { de: 'Beantragte Summe', en: 'Requested amount' }, required: true },
      { key: 'description', type: 'textarea', label: { de: 'Beschreibung', en: 'Description' }, help: { de: 'Worum geht es?', en: 'What is it about?' } },
    ],
  },
  'f-veranstaltung': {
    applicationTypeId: 'f-veranstaltung',
    formVersionId: 'fv-veranstaltung-2',
    version: 2,
    active: true,
    description: { de: '', en: '' },
    fields: [
      { key: 'event_name', type: 'text', label: { de: 'Name der Veranstaltung', en: 'Event name' }, required: true },
      { key: 'date', type: 'date', label: { de: 'Datum', en: 'Date' }, required: true },
    ],
  },
};

export const MOCK_WEBHOOKS: WebhookConfig[] = [
  {
    id: 'wh-1',
    name: 'Matrix-Bridge',
    url: 'https://hooks.example.org/matrix',
    events: ['application_created', 'status_changed'],
    active: true,
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
    applyInfo: {},
  },
};
