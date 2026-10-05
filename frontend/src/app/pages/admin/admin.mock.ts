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
  CdVariant,
  ConfigRevision,
  DeadlinePolicy,
  FlowGraph,
  FormDraft,
  GuestSettings,
  MailTemplate,
  FormOverviewItem,
  Gremium,
  GremiumMembership,
  GremiumMembershipMapping,
  GremiumRole,
  GremiumRoleMapping,
  GroupMapping,
  Role,
  WebhookConfig,
  WebhookDeliveryStatus,
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
  ...(
    [
      ['p-6', 'pat.protokoll', 'Pat Protokoll', ['stupa-mitglieder', 'stupa-protokoll']],
      ['p-7', 'toni.vorsitz', 'Toni Vorsitz', ['stupa-mitglieder', 'stupa-sitzungsleitung', 'asta-referate', 'asta-vorstand']],
      ['p-8', 'mika.muster', 'Mika Muster', ['stupa-mitglieder']],
      ['p-9', 'charlie.probe', 'Charlie Probe', ['stupa-mitglieder']],
      ['p-10', 'dana.demo', 'Dana Demo', ['stupa-mitglieder']],
      ['p-11', 'eli.exempel', 'Eli Exempel', ['stupa-mitglieder']],
    ] as const
  ).map(
    ([id, user, name, groups]): AdminPrincipal => ({
      id,
      sub: `kc|${user}`,
      email: `${user}@stupa.example`,
      displayName: name,
      lastLogin: '2026-06-03T16:00:00+00:00',
      oidcGroups: [...groups],
      assignments: [],
    }),
  ),
];

/**
 * The id of the mock Studierendenparlament. It is the id of the core mock API
 * (`mock-api.interceptor.ts`), where the mock principal manages this Gremium
 * (`session_manage_gremien`). With the same id, "Neue Sitzung" offers it.
 */
export const MOCK_GREMIUM_STUPA_ID = 'g0000000-0000-0000-0000-000000000001';

export const MOCK_GREMIEN: Gremium[] = [
  { id: MOCK_GREMIUM_STUPA_ID, name: 'Studierendenparlament', slug: 'stupa', cdVariantId: 'cd-stupa', defaultLang: 'de', allowVoteDelegation: true, delegationLeadMinutes: 60, delegationAllowExternal: false, quorumPercent: 50 },
  { id: 'g-asta', name: 'AStA', slug: 'asta', cdVariantId: 'cd-asta', defaultLang: 'de', allowVoteDelegation: false, delegationLeadMinutes: 0, delegationAllowExternal: false, quorumPercent: null },
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

/**
 * The forced roles of each mock gremium (mirror of `FORCED_GREMIUM_ROLES` in the backend)
 * and one own role of the Studierendenparlament.
 */
export const MOCK_GREMIUM_ROLES: GremiumRole[] = [
  ...MOCK_GREMIEN.flatMap((g) => [
    { id: `gr-${g.slug}-vorstand`, gremiumId: g.id, key: 'vorstand', name: { de: 'Vorstand', en: 'Board' }, forced: true, permissions: ['session.manage', 'vote.manage', 'vote.cast', 'protocol.write', 'protocol.finalize'] },
    { id: `gr-${g.slug}-manager`, gremiumId: g.id, key: 'manager', name: { de: 'Manager', en: 'Manager' }, forced: true, permissions: ['session.manage', 'vote.manage', 'vote.cast', 'protocol.write', 'protocol.finalize'] },
    { id: `gr-${g.slug}-member`, gremiumId: g.id, key: 'member', name: { de: 'Mitglied', en: 'Member' }, forced: true, permissions: ['vote.cast'] },
  ]),
  { id: 'gr-stupa-protokoll', gremiumId: MOCK_GREMIUM_STUPA_ID, key: 'protokoll', name: { de: 'Protokoll', en: 'Minutes' }, forced: false, permissions: ['vote.cast', 'protocol.write'] },
];

/** Read-only memberships. In the real backend the OIDC group sync writes them. */
export const MOCK_GREMIUM_MEMBERSHIPS: GremiumMembership[] = [
  { id: 'gms-1', principalId: 'p-1', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-vorstand' },
  { id: 'gms-2', principalId: 'p-2', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-member' },
  { id: 'gms-3', principalId: 'p-6', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-protokoll' },
  { id: 'gms-4', principalId: 'p-7', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-manager' },
  { id: 'gms-5', principalId: 'p-4', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-member' },
  { id: 'gms-6', principalId: 'p-8', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-member' },
  { id: 'gms-7', principalId: 'p-9', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-member' },
  { id: 'gms-8', principalId: 'p-10', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-member' },
  { id: 'gms-9', principalId: 'p-11', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-member' },
  { id: 'gms-10', principalId: 'p-4', gremiumId: 'g-asta', gremiumRoleId: 'gr-asta-member' },
  { id: 'gms-11', principalId: 'p-7', gremiumId: 'g-asta', gremiumRoleId: 'gr-asta-vorstand' },
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
  { id: 'grm-1', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-vorstand', oidcGroup: 'stupa-praesidium' },
  { id: 'grm-2', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-manager', oidcGroup: 'stupa-sitzungsleitung' },
  { id: 'grm-3', gremiumId: MOCK_GREMIUM_STUPA_ID, gremiumRoleId: 'gr-stupa-protokoll', oidcGroup: 'stupa-protokoll' },
  { id: 'grm-4', gremiumId: 'g-asta', gremiumRoleId: 'gr-asta-vorstand', oidcGroup: 'asta-vorstand' },
];

/** Extra protocol recipients per gremium (`/admin/gremien/{id}/mail-recipients`). */
export const MOCK_GREMIUM_MAIL_RECIPIENTS: Record<string, string[]> = {
  [MOCK_GREMIUM_STUPA_ID]: ['protokolle@stupa.example', 'verteiler@lists.stupa.example'],
};

/** Seed for the forms overview, until `/admin/application-types` is real. */
export const MOCK_FORMS: FormOverviewItem[] = [
  { id: 'f-foerderung', name: { de: 'Förderantrag', en: 'Funding application' }, gremiumId: MOCK_GREMIUM_STUPA_ID, status: 'active', version: 3 },
  { id: 'f-veranstaltung', name: { de: 'Veranstaltungsantrag', en: 'Event application' }, gremiumId: 'g-asta', status: 'active', version: 2 },
  { id: 'f-anschaffung', name: { de: 'Anschaffungsantrag', en: 'Procurement application' }, gremiumId: MOCK_GREMIUM_STUPA_ID, status: 'draft', version: 1 },
  { id: 'f-altfall', name: { de: 'Härtefallantrag', en: 'Hardship application' }, gremiumId: 'g-asta', status: 'inactive', version: 5 },
];

/** Application types/forms for the forms builder — mock until the backend is real. */
export const MOCK_APP_TYPES: ApplicationTypeFull[] = [
  { id: 'f-foerderung', name: { de: 'Förderantrag', en: 'Funding application' }, gremiumId: MOCK_GREMIUM_STUPA_ID, hasBudget: true, activeFormVersionId: 'fv-foerderung-3', activeFormVersion: 3 },
  { id: 'f-veranstaltung', name: { de: 'Veranstaltungsantrag', en: 'Event application' }, gremiumId: 'g-asta', hasBudget: false, activeFormVersionId: 'fv-veranstaltung-2', activeFormVersion: 2 },
  { id: 'f-anschaffung', name: { de: 'Anschaffungsantrag', en: 'Procurement application' }, gremiumId: MOCK_GREMIUM_STUPA_ID, hasBudget: true, activeFormVersionId: null, activeFormVersion: null },
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
    // Two steps with one field of each family that has its own options: choice options,
    // cost positions, a currency range and a computed field.
    fields: [
      { key: 'section_0', type: 'section', label: { de: 'Vorhaben', en: 'Project' } },
      { key: 'title', type: 'text', label: { de: 'Projekttitel', en: 'Project title' }, required: true },
      { key: 'description', type: 'textarea', label: { de: 'Beschreibung', en: 'Description' }, help: { de: 'Worum geht es?', en: 'What is it about?' }, required: true },
      { key: 'datum', type: 'date', label: { de: 'Datum', en: 'Date' } },
      { key: 'teilnehmende', type: 'number', label: { de: 'Erwartete Teilnehmende', en: 'Expected participants' } },
      {
        key: 'kategorie',
        type: 'multiselect',
        label: { de: 'Kategorie', en: 'Category' },
        help: { de: 'Mehrere Kategorien möglich.', en: 'Several categories possible.' },
        options: [
          { value: 'kultur', label: { de: 'Kultur', en: 'Culture' } },
          { value: 'bildung', label: { de: 'Bildung', en: 'Education' } },
          { value: 'sport', label: { de: 'Sport', en: 'Sports' } },
        ],
      },
      { key: 'section_1', type: 'section', label: { de: 'Kosten', en: 'Costs' } },
      { key: 'kosten', type: 'positions', label: { de: 'Kostenaufstellung', en: 'Cost breakdown' }, required: true, validation: { minOffers: 2, minPositions: 1 } },
      { key: 'amount', type: 'currency', label: { de: 'Beantragte Summe', en: 'Requested amount' }, required: true, validation: { min: 0 }, isPromoted: true, promoteTarget: 'amount' },
      {
        key: 'einnahmen',
        type: 'computed',
        label: { de: 'Erwartete Einnahmen', en: 'Expected income' },
        visibleIf: { '>': [{ var: 'teilnehmende' }, 0] },
        compute: { '*': [{ var: 'teilnehmende' }, 5] },
      },
      { key: 'iban', type: 'iban', label: { de: 'IBAN für die Auszahlung', en: 'IBAN for the payout' }, required: true, isPII: true },
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
  {
    id: 'wh-2',
    name: 'Archiv-Export',
    url: 'https://archive.example.org/api/hooks/protocols/receive-and-store-every-final-protocol',
    events: ['protocol_finalized', 'vote_closed', 'budget_booked'],
    active: true,
  },
  { id: 'wh-3', name: 'Kalender', url: 'https://calendar.example.org/hook', events: ['deadline_approaching'], active: true },
  { id: 'wh-4', name: 'Test-Endpunkt', url: 'https://test.example.org/hook', events: [], active: false },
];

/** The delivery state of the mock webhooks: one of each state. */
export const MOCK_WEBHOOK_STATUS: WebhookDeliveryStatus[] = [
  { webhookId: 'wh-1', lastState: 'sent', reasonClass: 'delivered', responseCode: 200, attempts: 1, lastAt: '2026-10-04T16:20:00Z' },
  { webhookId: 'wh-2', lastState: 'dead', reasonClass: 'target_server_error', responseCode: 502, attempts: 5, lastAt: '2026-10-04T18:12:00Z' },
  { webhookId: 'wh-3', lastState: 'pending', reasonClass: 'in_progress', responseCode: null, attempts: 2, lastAt: '2026-10-05T07:45:00Z' },
  { webhookId: 'wh-4', lastState: 'never', reasonClass: 'no_deliveries', responseCode: null, attempts: 0, lastAt: null },
];

/** Deadline policies of the mock flow: one of each kind. */
export const MOCK_DEADLINE_POLICIES: DeadlinePolicy[] = [
  { id: 'dp-1', key: 'nachforderung_14d', label: { de: 'Nachforderung beantworten', en: 'Answer the request' }, kind: 'relative_changed', offsetDays: 14, atTime: '23:59', timezone: 'Europe/Berlin' },
  { id: 'dp-2', key: 'pruefung_21d', label: { de: 'Prüfung durch den Finanzausschuss', en: 'Review by the finance committee' }, kind: 'relative_submitted', offsetDays: 21 },
  { id: 'dp-3', key: 'einreichschluss_ws', label: { de: 'Einreichschluss Wintersemester', en: 'Winter term deadline' }, kind: 'absolute', absoluteAt: '2026-10-15T10:00:00Z', atTime: '12:00', timezone: 'Europe/Berlin' },
  { id: 'dp-4', key: 'stupa_sitzungen', label: { de: 'Sitzungstermine Studierendenparlament', en: 'Student parliament meetings' }, kind: 'recurring', dates: ['2026-09-29', '2026-10-13', '2026-10-27', '2026-11-10'], atTime: '18:00', timezone: 'Europe/Berlin' },
];

/** The guest settings of the mock backend (the server defaults). */
export const MOCK_GUEST_SETTINGS: GuestSettings = { confirmTtlHours: 12, linkTtlDays: null };

/** CD variants of the mock gremien. */
export const MOCK_CD_VARIANTS: CdVariant[] = [
  {
    id: 'cd-stupa',
    key: 'stupa',
    name: 'StuPa',
    baseVariant: 'protocol',
    logos: [
      { id: 'cdl-1', slot: 'title', position: 0, vendoredName: 'HSRT' },
      { id: 'cdl-2', slot: 'title', position: 1, fileName: 'stupa-mark.svg', mime: 'image/svg+xml', size: 3_172 },
      { id: 'cdl-3', slot: 'footer', position: 0, fileName: 'stupa-wordmark.pdf', mime: 'application/pdf', size: 45_311 },
    ],
  },
  { id: 'cd-asta', key: 'asta', name: 'AStA', baseVariant: 'protocol', logos: [{ id: 'cdl-4', slot: 'title', position: 0, vendoredName: 'ASTA' }] },
  { id: 'cd-bericht', key: 'bericht', name: 'Bericht', baseVariant: 'report', logos: [] },
];

/** A part of the builtin mail catalogue, one template with an override. */
export const MOCK_MAIL_TEMPLATES: MailTemplate[] = [
  {
    id: null,
    key: 'magic_link',
    subjectI18n: { de: 'Dein Link zur Antragsplattform', en: 'Your link to the application platform' },
    bodyI18n: { de: 'Hallo,\n\nmit diesem Link öffnest du deinen Antrag:\n{{ link }}', en: 'Hello,\n\nopen your application with this link:\n{{ link }}' },
    bodyHtmlI18n: {},
    placeholders: { link: 'https://antraege.example.org/status#t=…' },
    source: 'builtin',
  },
  {
    id: 'mt-1',
    key: 'status_update',
    subjectI18n: { de: 'Dein Antrag „{{ applicationTitle }}“: {{ status }}', en: 'Your application "{{ applicationTitle }}": {{ status }}' },
    bodyI18n: {
      de: 'Hallo,\n\nder Status deines Antrags „{{ applicationTitle }}“ hat sich geändert:\n{{ status }}\n\nDen aktuellen Stand siehst du über deinen Link.',
      en: 'Hello,\n\nthe status of your application "{{ applicationTitle }}" changed:\n{{ status }}',
    },
    bodyHtmlI18n: {},
    placeholders: { applicationTitle: 'Erstsemester-Party', status: 'Auf Tagesordnung', applicationId: 'a1b2c3d4' },
    source: 'override',
  },
  {
    id: null,
    key: 'task_reminder',
    subjectI18n: { de: 'Erinnerung: offene Aufgabe', en: 'Reminder: open task' },
    bodyI18n: { de: 'Hallo,\n\nder Antrag „{{ applicationTitle }}“ wartet auf dich.', en: 'Hello,\n\nthe application "{{ applicationTitle }}" waits for you.' },
    bodyHtmlI18n: {},
    placeholders: { applicationTitle: 'Erstsemester-Party' },
    source: 'builtin',
  },
  {
    id: null,
    key: 'erasure_requested',
    subjectI18n: { de: 'Neuer Löschantrag', en: 'New erasure request' },
    bodyI18n: { de: 'Hallo,\n\nein neuer Löschantrag wartet auf eine Entscheidung.', en: 'Hello,\n\na new erasure request waits for a decision.' },
    bodyHtmlI18n: {},
    placeholders: {},
    source: 'builtin',
  },
];

/** The versions of the site config in the mock backend, newest first. */
export const MOCK_SITE_REVISIONS: ConfigRevision[] = [
  { id: 'rev-form-3', entityType: 'form', entityId: 'f-foerderung', version: 3, at: '2026-09-24T08:14:00Z', createdBy: 'p-1', createdByName: 'Mara Keller', isCurrent: true },
  { id: 'rev-form-2', entityType: 'form', entityId: 'f-foerderung', version: 2, at: '2026-09-12T15:02:00Z', createdBy: 'p-1', createdByName: 'Mara Keller', isCurrent: false },
  { id: 'rev-flow-12', entityType: 'flow', entityId: 'global', version: 12, at: '2026-09-28T10:30:00Z', createdBy: 'p-1', createdByName: 'Mara Keller', isCurrent: true },
  { id: 'rev-flow-11', entityType: 'flow', entityId: 'global', version: 11, at: '2026-09-02T07:45:00Z', createdBy: null, createdByName: null, isCurrent: false },
  { id: 'rev-site-3', entityType: 'site_config', entityId: 'global', version: 3, at: '2026-10-02T09:12:00Z', createdBy: 'p-1', createdByName: 'Mara Keller', isCurrent: true },
  { id: 'rev-site-2', entityType: 'site_config', entityId: 'global', version: 2, at: '2026-09-14T15:40:00Z', createdBy: 'p-1', createdByName: 'Mara Keller', isCurrent: false },
  { id: 'rev-site-1', entityType: 'site_config', entityId: 'global', version: 1, at: '2026-08-30T08:00:00Z', createdBy: null, createdByName: null, isCurrent: false },
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

/**
 * The global flow of mock mode: a review step, a request for more details that comes
 * back automatically, and a vote of the StuPa with its pass and fail branches. The
 * positions put it on the grid of the board Admin-Flow-Editor.
 */
export const MOCK_FLOW: FlowGraph = {
  states: [
    { key: 'entwurf', label: { de: 'Entwurf', en: 'Draft' }, isInitial: true },
    { key: 'eingereicht', label: { de: 'Eingereicht', en: 'Submitted' } },
    { key: 'pruefung', label: { de: 'In Prüfung', en: 'In review' }, color: '#f18700', config: { deadlinePolicyKey: 'pruefung_21d' } },
    { key: 'nachforderung', label: { de: 'Nachforderung', en: 'More details' }, color: '#f18700' },
    {
      key: 'tagesordnung',
      label: { de: 'Auf Tagesordnung', en: 'On the agenda' },
      kind: 'vote',
      editAllowed: false,
      config: { gremiumId: MOCK_GREMIUM_STUPA_ID },
    },
    { key: 'bewilligt', label: { de: 'Bewilligt', en: 'Approved' }, color: '#72a384', isTerminal: true, editAllowed: false },
    { key: 'abgelehnt', label: { de: 'Abgelehnt', en: 'Rejected' }, color: '#ce1625', isTerminal: true, editAllowed: false },
    { key: 'zurueckgezogen', label: { de: 'Zurückgezogen', en: 'Withdrawn' }, isTerminal: true, editAllowed: false },
  ],
  transitions: [
    { from: 'entwurf', to: 'eingereicht', label: { de: 'Einreichen', en: 'Submit' }, guard: { actorIsApplicant: true } },
    { from: 'eingereicht', to: 'pruefung', label: { de: 'Prüfung beginnen', en: 'Start review' }, guard: { roleIs: 'referent' } },
    { from: 'eingereicht', to: 'zurueckgezogen', label: { de: 'Zurückziehen', en: 'Withdraw' }, guard: { actorIsApplicant: true }, requiresAction: false },
    { from: 'pruefung', to: 'nachforderung', label: { de: 'Nachforderung stellen', en: 'Ask for details' }, color: '#f18700', actions: [{ type: 'notify', recipients: [{ kind: 'applicant' }] }] },
    { from: 'nachforderung', to: 'eingereicht', label: { de: 'Angaben ergänzt', en: 'Details added' }, automatic: true, guard: { hasField: 'iban' } },
    {
      from: 'pruefung',
      to: 'tagesordnung',
      label: { de: 'Auf Tagesordnung setzen', en: 'Put on the agenda' },
      color: '#72a384',
      guard: { and: [{ isInCommittee: MOCK_GREMIUM_STUPA_ID }, { compare: { field: 'amount', op: '>', value: 1000 } }] },
      actions: [
        { type: 'addToNextSession', gremiumId: MOCK_GREMIUM_STUPA_ID },
        { type: 'notify', recipients: [{ kind: 'applicant' }, { kind: 'gremium', ref: MOCK_GREMIUM_STUPA_ID }] },
      ],
    },
    { from: 'pruefung', to: 'abgelehnt', label: { de: 'Ablehnen', en: 'Reject' }, color: '#ce1625' },
    { from: 'tagesordnung', to: 'bewilligt', branch: 'pass' },
    { from: 'tagesordnung', to: 'abgelehnt', branch: 'fail' },
  ],
  layout: {
    positions: {
      entwurf: { x: 40, y: 60 },
      eingereicht: { x: 300, y: 60 },
      pruefung: { x: 560, y: 60 },
      zurueckgezogen: { x: 40, y: 260 },
      nachforderung: { x: 560, y: 260 },
      tagesordnung: { x: 560, y: 460 },
      bewilligt: { x: 300, y: 660 },
      abgelehnt: { x: 820, y: 660 },
    },
  },
};
