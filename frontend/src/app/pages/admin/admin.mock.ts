/**
 * Mock seed data for the admin area. It stays active only while the admin API and the
 * site-config are not fully merged (`USE_MOCK_API`). Delete this file together with the
 * mock branches in `AdminApiService` once the backend merge lands.
 */
import type {
  AdminPrincipal,
  AuditActor,
  AuditEntry,
  AuditVerification,
  Backup,
  ErasureRequest,
  ApplicationTypeFull,
  Branding,
  FormDraft,
  FormOverviewItem,
  Gremium,
  GremiumMembership,
  GremiumMembershipMapping,
  GremiumRole,
  GremiumRoleMapping,
  GroupMapping,
  Role,
  WebhookConfig,
} from './admin.models';

/** Permission catalog (mirror of `app.shared.permissions.PERMISSION_CATALOGUE`). */
export const MOCK_PERMISSIONS: string[] = [
  'application.read',
  'application.read_all',
  'application.transition',
  'application.force_status',
  'application.manage',
  'application.edit_any',
  'application.delete',
  'application.archive',
  'application.share',
  'form.configure',
  'flow.configure',
  'meeting.view_all',
  'meeting.delete_finalized',
  'budget.view',
  'budget.structure',
  'budget.book',
  'budget.export',
  'application.export',
  'webhook.manage',
  'audit.read',
  'audit.verify',
  'audit.revert',
  'admin.site',
  'admin.gremien',
  'admin.types',
  'admin.types_delete',
  'admin.roles',
  'admin.users',
  'admin.group_mappings',
  'admin.gremium_roles',
  'admin.cd_variants',
  'admin.delegations',
  'admin.deadlines',
  'admin.notifications',
  'privacy.manage',
  'backup.manage',
  'mcp.use',
];

export const MOCK_PRINCIPALS: AdminPrincipal[] = [
  {
    id: 'p-1',
    sub: 'kc|alex.admin',
    email: 'alex@stupa.example',
    displayName: 'Alex Admin',
    lastLogin: '2026-06-06T18:20:00+00:00',
    oidcGroups: ['stupa-admins'],
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
    oidcGroups: ['stupa-mitglieder'],
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
    oidcGroups: [],
    assignments: [],
  },
  {
    id: 'p-4',
    sub: 'kc|kim.kasse',
    email: 'kim@stupa.example',
    displayName: 'Kim Kasse',
    lastLogin: '2026-06-04T07:45:00+00:00',
    oidcGroups: ['stupa-mitglieder', 'stupa-referate', 'asta-referate'],
    assignments: [],
  },
  {
    id: 'p-5',
    sub: 'kc|jo.alt',
    email: 'jo@stupa.example',
    displayName: 'Jo Ehemalig',
    lastLogin: '2026-02-11T12:10:00+00:00',
    active: false,
    oidcGroups: ['stupa-mitglieder'],
    assignments: [],
  },
];

/**
 * The id of the mock Studierendenparlament. It is the id of the core mock API
 * (`mock-api.interceptor.ts`), where the mock principal manages this Gremium
 * (`session_manage_gremien`). With the same id, "Neue Sitzung" offers it.
 */
export const MOCK_GREMIUM_STUPA_ID = 'g0000000-0000-0000-0000-000000000001';

export const MOCK_GREMIEN: Gremium[] = [
  { id: MOCK_GREMIUM_STUPA_ID, name: 'Studierendenparlament', slug: 'stupa', cdVariantId: 'cd-stupa', defaultLang: 'de', allowVoteDelegation: true },
  { id: 'g-asta', name: 'AStA', slug: 'asta', cdVariantId: 'cd-asta', defaultLang: 'de', allowVoteDelegation: false },
];

/**
 * Fallback role list for the options provider, while the real `/admin/roles` stays
 * empty or absent. It mirrors the seed roles from `auth/seed`
 * (member/referent/vorstand/admin).
 */
export const MOCK_ROLES: Role[] = [
  { id: 'r-member', key: 'member', label: { de: 'Mitglied', en: 'Member' }, permissions: ['application.read'] },
  { id: 'r-referent', key: 'referent', label: { de: 'Referent:in', en: 'Officer' }, permissions: ['application.read', 'application.update', 'application.transition'] },
  { id: 'r-vorstand', key: 'vorstand', label: { de: 'Vorstand', en: 'Board' }, permissions: ['application.read', 'budget.view', 'meeting.view_all'] },
  { id: 'r-admin', key: 'admin', label: { de: 'Administration', en: 'Administration' }, permissions: [...MOCK_PERMISSIONS] },
];

/** The forced roles of each mock gremium (board, manager, member). */
export const MOCK_GREMIUM_ROLES: GremiumRole[] = MOCK_GREMIEN.flatMap((g) => [
  { id: `gr-${g.slug}-board`, gremiumId: g.id, key: 'board', name: { de: 'Vorstand', en: 'Board' }, forced: true, permissions: ['session.manage', 'vote.manage', 'vote.cast', 'protocol.write', 'protocol.finalize'] },
  { id: `gr-${g.slug}-manager`, gremiumId: g.id, key: 'manager', name: { de: 'Sitzungsleitung', en: 'Chair' }, forced: true, permissions: ['session.manage', 'vote.manage', 'vote.cast'] },
  { id: `gr-${g.slug}-member`, gremiumId: g.id, key: 'member', name: { de: 'Mitglied', en: 'Member' }, forced: true, permissions: ['vote.cast'] },
]);

/** Read-only memberships. In the real backend the OIDC group sync writes them. */
export const MOCK_GREMIUM_MEMBERSHIPS: GremiumMembership[] = [
  { id: 'gms-1', principalId: 'p-1', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-board' },
  { id: 'gms-2', principalId: 'p-2', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-member' },
];

/** OIDC group → global role. */
export const MOCK_GROUP_MAPPINGS: GroupMapping[] = [
  { id: 'gm-1', oidcGroup: 'stupa-admins', roleId: 'r-admin' },
  { id: 'gm-2', oidcGroup: 'stupa-referate', roleId: 'r-referent' },
];

/** OIDC group → gremium membership. */
export const MOCK_GREMIUM_MEMBERSHIP_MAPPINGS: GremiumMembershipMapping[] = [
  { id: 'gmm-1', gremiumId: MOCK_GREMIUM_STUPA_ID, oidcGroup: 'stupa-mitglieder' },
  { id: 'gmm-2', gremiumId: 'g-asta', oidcGroup: 'asta-referate' },
];

/** OIDC group → role of one gremium. */
export const MOCK_GREMIUM_ROLE_MAPPINGS: GremiumRoleMapping[] = [
  { id: 'grm-1', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-board', oidcGroup: 'stupa-praesidium' },
];

/** Seed for the forms overview, until `/admin/application-types` is real. */
export const MOCK_FORMS: FormOverviewItem[] = [
  { id: 'f-foerderung', name: { de: 'Förderantrag', en: 'Funding application' }, gremiumId: MOCK_GREMIUM_STUPA_ID, status: 'active', version: 3 },
  { id: 'f-veranstaltung', name: { de: 'Veranstaltungsantrag', en: 'Event application' }, gremiumId: 'g-asta', status: 'active', version: 2 },
  { id: 'f-anschaffung', name: { de: 'Anschaffungsantrag', en: 'Procurement application' }, gremiumId: MOCK_GREMIUM_STUPA_ID, status: 'draft', version: 1 },
  { id: 'f-altfall', name: { de: 'Härtefallantrag', en: 'Hardship application' }, gremiumId: 'g-asta', status: 'inactive', version: 5 },
];

/** Application types/forms for the forms builder — mock until the backend is real. */
export const MOCK_APP_TYPES: ApplicationTypeFull[] = [
  { id: 'f-foerderung', name: { de: 'Förderantrag', en: 'Funding application' }, gremiumId: MOCK_GREMIUM_STUPA_ID, hasBudget: true, activeFormVersionId: 'fv-foerderung-3' },
  { id: 'f-veranstaltung', name: { de: 'Veranstaltungsantrag', en: 'Event application' }, gremiumId: 'g-asta', hasBudget: false, activeFormVersionId: 'fv-veranstaltung-2' },
  { id: 'f-anschaffung', name: { de: 'Anschaffungsantrag', en: 'Procurement application' }, gremiumId: MOCK_GREMIUM_STUPA_ID, hasBudget: true, activeFormVersionId: null },
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

/** Seed for the backup catalogue in mock mode. */
export const MOCK_BACKUPS: Backup[] = [
  {
    id: 'b-nightly',
    kind: 'scheduled',
    status: 'done',
    createdAt: '2026-09-01T04:00:00Z',
    finishedAt: '2026-09-01T04:03:12Z',
    createdBy: null,
    sizeBytes: 48_234_496,
    objectCount: 137,
    checksum: '3f5a9c1e2b7d4088a1c6e0f2b8d4a7c19e3f5b8d2a6c0e4f7b1d9a3c5e7f0b2d',
    pinned: false,
  },
  {
    id: 'b-before-vote',
    kind: 'manual',
    status: 'done',
    createdAt: '2026-08-28T18:12:00Z',
    finishedAt: '2026-08-28T18:15:41Z',
    createdBy: 'admin-sub',
    sizeBytes: 47_112_192,
    objectCount: 131,
    note: 'Vor der Haushaltsabstimmung',
    pinned: true,
  },
];

/** Seed for the erasure queue in mock mode: two open requests and two handled ones. */
export const MOCK_ERASURES: ErasureRequest[] = [
  {
    id: 'e-1',
    createdAt: '2026-06-05T09:12:00+00:00',
    subjectType: 'applicant',
    applicationId: 'a1000000-0000-0000-0000-000000000001',
    email: 'antrag@example.org',
    status: 'open',
  },
  {
    id: 'e-2',
    createdAt: '2026-06-03T16:40:00+00:00',
    subjectType: 'principal',
    principalId: 'p-5',
    email: 'jo@stupa.example',
    status: 'open',
  },
  {
    id: 'e-3',
    createdAt: '2026-05-20T11:00:00+00:00',
    subjectType: 'applicant',
    email: null,
    status: 'executed',
    handledAt: '2026-05-21T08:00:00+00:00',
  },
  {
    id: 'e-4',
    createdAt: '2026-05-02T14:30:00+00:00',
    subjectType: 'applicant',
    email: 'frage@example.org',
    status: 'rejected',
    reason: 'Aufbewahrungspflicht',
  },
];

/** The newest stored check of the audit chain in mock mode (the nightly job). */
export const MOCK_AUDIT_VERIFICATION: AuditVerification = {
  id: 'av-1',
  startedAt: '2026-06-07T02:30:00+00:00',
  finishedAt: '2026-06-07T02:30:04+00:00',
  valid: true,
  checked: 1284,
  brokenAt: null,
  reason: null,
  trigger: 'cron',
  triggeredBy: null,
};

/** Actors of the mock audit log. */
export const MOCK_AUDIT_ACTORS: AuditActor[] = [
  { sub: 'kc|alex.admin', name: 'Alex Admin' },
  { sub: 'kc|kim.kasse', name: 'Kim Kasse' },
];

/** A short mock audit log, newest first. Entry 7 is a revertable config change. */
export const MOCK_AUDIT_ENTRIES: AuditEntry[] = [
  {
    id: 8,
    at: '2026-06-07T14:12:00+00:00',
    actor: 'kc|alex.admin',
    actorName: 'Alex Admin',
    action: 'pii_export',
    targetType: 'export',
    targetId: 'auskunft.xlsx',
    targetLabel: null,
    data: {},
    hash: 'h8',
    prevHash: 'h7',
  },
  {
    id: 7,
    at: '2026-06-07T09:30:00+00:00',
    actor: 'kc|alex.admin',
    actorName: 'Alex Admin',
    action: 'config_activation',
    targetType: 'flow',
    targetId: 'global',
    targetLabel: null,
    data: { revisionId: 'rev-12', version: 12 },
    revertable: true,
    hash: 'h7',
    prevHash: 'h6',
  },
  {
    id: 6,
    at: '2026-06-06T18:30:00+00:00',
    actor: 'kc|robin.member',
    actorName: 'Robin Mitglied',
    action: 'delegation_grant',
    targetType: 'meeting',
    targetId: 'm0000000-0000-0000-0000-000000000001',
    targetLabel: 'Sitzung des Studierendenparlaments',
    data: {},
    hash: 'h6',
    prevHash: 'h5',
  },
  {
    id: 5,
    at: '2026-06-06T14:20:00+00:00',
    actor: 'kc|alex.admin',
    actorName: 'Alex Admin',
    action: 'status_change',
    targetType: 'application',
    targetId: 'a1000000-0000-0000-0000-000000000001',
    targetLabel: 'Zuschuss für das Sommerfest',
    data: { from: 'submitted', to: 'review' },
    revertable: true,
    hash: 'h5',
    prevHash: 'h4',
  },
  {
    id: 4,
    at: '2026-06-06T08:05:00+00:00',
    actor: 'kc|kim.kasse',
    actorName: 'Kim Kasse',
    action: 'budget_expense_create',
    targetType: 'budget_expense',
    targetId: 'x0000000-0000-0000-0000-000000000001',
    targetLabel: 'Getränke für das Erstsemester-Frühstück',
    data: {},
    hash: 'h4',
    prevHash: 'h3',
  },
  {
    id: 3,
    at: '2026-06-06T01:30:00+00:00',
    actor: null,
    actorName: null,
    action: 'retention_anonymize',
    targetType: 'application',
    targetId: 'a1000000-0000-0000-0000-000000000009',
    targetLabel: 'Sommerfest 2024',
    data: {},
    hash: 'h3',
    prevHash: 'h2',
  },
  {
    id: 2,
    at: '2026-06-05T16:15:00+00:00',
    actor: 'kc|alex.admin',
    actorName: 'Alex Admin',
    action: 'role_change',
    targetType: 'role',
    targetId: 'r-referent',
    targetLabel: 'Referent:in',
    data: {},
    hash: 'h2',
    prevHash: 'h1',
  },
];
