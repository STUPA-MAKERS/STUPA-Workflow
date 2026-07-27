/**
 * Admin config DTOs — mirror of the admin API and the config schemas. camelCase like
 * the backend `_CamelModel`. The backend OpenAPI stays the source of truth.
 *
 * In mock mode (`USE_MOCK_API`) an in-memory store provides data so the UIs are
 * developable and testable. Branding/site-config uses the local `/api/admin/site-config`
 * path, which is not part of the API spec.
 */
import type {
  DataDiff,
  DataDiffWire,
  FormFieldDef,
  I18nMap,
  Uuid,
} from '@core/api/models';

// Flow graph

/** State kind in the global flow: only normal + vote. */
export type StateKind = 'normal' | 'vote';

/** Per-state config depending on `kind`. Empty object for `normal`. */
export interface StateConfig {
  /** vote: the gremium that votes. */
  gremiumId?: string;
  /**
   * Key of a named deadline policy: on entering the state the server creates a
   * deadline that the state's `deadlinePassed` transition fires.
   */
  deadlinePolicyKey?: string;
}

export interface StateDef {
  key: string;
  label: I18nMap;
  /** Display color of the state badge (hex), optional. */
  color?: string | null;
  editAllowed?: boolean;
  isInitial?: boolean;
  /** Terminal state: terminal applications are subject to retention/anonymization. */
  isTerminal?: boolean;
  /** State kind. Absent ⇒ `normal`. */
  kind?: StateKind | null;
  /** Kind-specific configuration. */
  config?: StateConfig | null;
}

/** Result branch of a vote state: pass/fail. */
export type TransitionBranch = 'pass' | 'fail';

export interface TransitionDef {
  from: string;
  to: string;
  label?: I18nMap | null;
  /** Optional color: tints the arrow in the editor + the decision button in the application. */
  color?: string | null;
  guard?: Guard | null;
  actions?: ActionDef[];
  order?: number | null;
  /** Automatic transition: fires without user action as soon as the guard holds. */
  automatic?: boolean;
  /** Result branch for vote states: pass/fail. */
  branch?: TransitionBranch | null;
  /** "Requires action": counts as an open task in the tasks tab.
   *  Absent ⇒ `true`. `false` = a purely optional action. */
  requiresAction?: boolean;
}

/** Visual node group. Only the editor renders it and the engine ignores it. On the
 *  canvas a group is always ONE labeled box. Its content opens through drill-down
 *  (breadcrumbs). Groups nest through `groupIds`. A state or group sits in at most
 *  one parent. */
export interface FlowGroup {
  id: string;
  name: string;
  stateKeys: string[];
  /** Directly contained sub-groups (nesting). */
  groupIds?: string[];
  color?: string | null;
}

/** Optional editor layout (node positions + groups). The graph stores it. */
export interface FlowLayout {
  positions?: Record<string, { x: number; y: number }>;
  groups?: FlowGroup[];
}

export interface FlowGraph {
  states: StateDef[];
  transitions: TransitionDef[];
  layout?: FlowLayout | null;
}

// Guards — mirror of the backend whitelist in shared/guards.py

/** Comparison operators of the `compare` guard (type-dependent at runtime). */
export type CompareOp = '==' | '!=' | '<' | '<=' | '>' | '>=' | 'in';
export const COMPARE_OPS: readonly CompareOp[] = ['==', '!=', '<', '<=', '>', '>=', 'in'] as const;

/** Condition operators (on automatic + manual transitions). */
export type GuardConditionOp =
  | 'deadlinePassed'
  | 'applicantRoleIs'
  | 'applicantCommitteeIs'
  | 'applicationTypeIs'
  | 'attachmentPresent'
  | 'budgetIs'
  | 'budgetFitsApplication'
  | 'hasField'
  | 'compare';
/** Actor gates — only on manual transitions. */
export type GuardActorOp = 'roleIs' | 'isInCommittee' | 'actorIsApplicant';
export type GuardLeafOperator = GuardConditionOp | GuardActorOp;
export type GuardCombinator = 'and' | 'or' | 'not';

/** A single guard node (exactly one operator, like `validate_guard`). */
export type Guard = Record<string, unknown>;

export const GUARD_CONDITION_OPERATORS: readonly GuardConditionOp[] = [
  'deadlinePassed',
  'applicantRoleIs',
  'applicantCommitteeIs',
  'applicationTypeIs',
  'attachmentPresent',
  'budgetIs',
  'budgetFitsApplication',
  'hasField',
  'compare',
] as const;
export const GUARD_ACTOR_OPERATORS: readonly GuardActorOp[] = [
  'roleIs',
  'isInCommittee',
  'actorIsApplicant',
] as const;
export const GUARD_LEAF_OPERATORS: readonly GuardLeafOperator[] = [
  ...GUARD_CONDITION_OPERATORS,
  ...GUARD_ACTOR_OPERATORS,
] as const;
export const GUARD_COMBINATORS: readonly GuardCombinator[] = ['and', 'or', 'not'] as const;


export type ActionType =
  | 'webhook'
  | 'notify'
  | 'addToNextSession'
  | 'assignBudget'
  | 'assignBudgetFromField';
export const ACTION_TYPES: readonly ActionType[] = [
  'webhook',
  'notify',
  'addToNextSession',
  'assignBudget',
  'assignBudgetFromField',
] as const;

/** Recipient kind of a `notify` action. */
export type NotifyRecipientKind = 'gremium' | 'role' | 'applicant' | 'email';
export const NOTIFY_RECIPIENT_KINDS: readonly NotifyRecipientKind[] = [
  'gremium',
  'role',
  'applicant',
  'email',
] as const;
export interface NotifyRecipient {
  kind: NotifyRecipientKind;
  ref?: string;
}

export interface ActionDef {
  type: ActionType;
  [param: string]: unknown;
}

// Organization / RBAC — mirror of admin/models.py

export interface Gremium {
  id: Uuid;
  name: string;
  slug: string;
  cdVariant: string;
  defaultLang: string;
  allowVoteDelegation: boolean;
  /** Lead time in minutes before the meeting starts, for non-pool delegations.
   *  0 = until the start. */
  delegationLeadMinutes?: number;
  /** Allow delegation to users outside the gremium & substitute pool. */
  delegationAllowExternal?: boolean;
  /** Default quorum as a percent of eligible voters who must attend. null = none. */
  quorumPercent?: number | null;
}

/** Body for `POST /admin/gremien` (`GremiumCreate`). */
export interface GremiumCreateBody {
  name: string;
  slug: string;
  cdVariant: string;
  defaultLang: string;
  allowVoteDelegation?: boolean;
  delegationLeadMinutes?: number;
  delegationAllowExternal?: boolean;
  quorumPercent?: number | null;
}

/** Body for `PATCH /admin/gremien/{id}` (`GremiumUpdate`) — all fields optional. */
export interface GremiumUpdateBody {
  name?: string;
  slug?: string;
  cdVariant?: string;
  defaultLang?: string;
  allowVoteDelegation?: boolean;
  delegationLeadMinutes?: number;
  delegationAllowExternal?: boolean;
  quorumPercent?: number | null;
}

/** CD variants (pytex) as a dropdown instead of free text. */
export const CD_VARIANTS: readonly string[] = ['stupa', 'asta', 'echo', 'makers', 'report'];

/** Name → URL slug (auto-generated). */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue')
    .replace(/ß/g, 'ss')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export interface Role {
  id: Uuid;
  key: string;
  label: I18nMap;
  permissions: string[];
}

/** Mail template (admin API `/admin/mail-templates`): i18n subject/body/HTML. */
export interface MailTemplate {
  /** Builtins (not yet overridden) have no DB id. */
  id: Uuid | null;
  key: string;
  subjectI18n: I18nMap;
  bodyI18n: I18nMap;
  bodyHtmlI18n: I18nMap;
  placeholders: Record<string, string>;
  /** 'override' = from the DB. 'builtin' = the unchanged catalog default. */
  source: 'override' | 'builtin';
}

/** Create/update an override by key (catalog merge). */
export interface MailTemplateUpsertBody {
  key: string;
  subjectI18n: I18nMap;
  bodyI18n: I18nMap;
  bodyHtmlI18n: I18nMap;
}

/** Preview from the editor draft (no id). */
export interface MailPreviewPayload {
  subjectI18n: I18nMap;
  bodyI18n: I18nMap;
  bodyHtmlI18n: I18nMap;
  lang: string;
  context: Record<string, unknown>;
}

/** Rendered preview of a template. */
export interface MailPreview {
  subject: string;
  text: string;
  html?: string | null;
  lang: string;
}

/** OIDC group → role (+ optional gremium) mapping (admin API `/group-mappings`). */
export interface GroupMapping {
  id: Uuid;
  oidcGroup: string;
  roleId: Uuid;
  gremiumId?: Uuid | null;
}

/** Input to create/update a group mapping. */
export interface GroupMappingBody {
  oidcGroup: string;
  roleId: Uuid;
  gremiumId?: Uuid | null;
}

/** Role assignment (admin API `/role-assignments`) — carries the vote delegation. */
export interface RoleAssignment {
  id: Uuid;
  principalId: Uuid;
  roleId: Uuid;
  gremiumId?: Uuid | null;
  grantedBy?: string | null;
  validFrom?: string | null;
  validUntil?: string | null;
  delegateVoting: boolean;
}

/** Input for a new assignment — optional tz-aware validity window. */
export interface RoleAssignmentInput {
  principalId: Uuid;
  roleId: Uuid;
  gremiumId?: Uuid | null;
  validFrom?: string | null;
  validUntil?: string | null;
  delegateVoting?: boolean;
}

/** OIDC principal (user) incl. its role assignments (admin API `/principals`). */
export interface AdminPrincipal {
  id: Uuid;
  sub: string;
  email?: string | null;
  displayName?: string | null;
  lastLogin?: string | null;
  active?: boolean;
  assignments: RoleAssignment[];
}

export interface ApplicationTypeAdmin {
  id: Uuid;
  key: string;
  name: I18nMap;
  gremiumId?: Uuid | null;
  active: boolean;
}

/** Comparison-offers rule of an application type. */
export interface ComparisonOffers {
  required: boolean;
  minCount: number;
  thresholdAmount?: string | null;
  as?: 'file' | 'field' | 'both';
}

/**
 * Application type (form) as the forms builder edit view. It mirrors the admin API type
 * `ApplicationTypeOut`. `name` is the i18n map that holds the form title.
 */
export interface ApplicationTypeFull {
  id: Uuid;
  name: I18nMap;
  gremiumId?: Uuid | null;
  hasBudget: boolean;
  comparisonOffers?: ComparisonOffers | null;
  /** DSGVO retention in months. null = the global default. */
  retentionMonths?: number | null;
  activeFormVersionId?: Uuid | null;
}

/** Body for `POST /admin/application-types` — create an application type/form. */
export interface ApplicationTypeCreateBody {
  key: string;
  name: I18nMap;
  gremiumId?: Uuid | null;
  hasBudget?: boolean;
}

/** Body for `PATCH /admin/application-types/{id}` — title/gremium/budget. */
export interface ApplicationTypeUpdateBody {
  name?: I18nMap;
  gremiumId?: Uuid | null;
  hasBudget?: boolean;
  comparisonOffers?: ComparisonOffers | null;
}

/**
 * A type's current form version for editing — raw fields + description (forms editor).
 * For a freshly created type `fields` is empty.
 */
export interface FormDraft {
  applicationTypeId: Uuid;
  formVersionId?: Uuid | null;
  version?: number | null;
  active?: boolean;
  description?: I18nMap | null;
  fields: FormFieldDef[];
}

export type FormStatus = 'active' | 'draft' | 'inactive';

/**
 * Overview row of active forms: display name, owning gremium, status and active form
 * version. The row aggregates application type and form version. Mock mode seeds it.
 */
export interface FormOverviewItem {
  id: Uuid;
  name: I18nMap;
  gremiumId?: Uuid | null;
  status: FormStatus;
  version: number;
}

// Notification and webhook config

export type EventName =
  | 'application_created'
  | 'application_updated'
  | 'status_changed'
  | 'vote_opened'
  | 'vote_closed'
  | 'application_approved'
  | 'application_rejected'
  | 'comment_added'
  | 'budget_reserved'
  | 'budget_booked'
  | 'protocol_finalized'
  | 'deadline_approaching'
  | 'deadline_passed';

export const EVENT_NAMES: readonly EventName[] = [
  'application_created',
  'application_updated',
  'status_changed',
  'vote_opened',
  'vote_closed',
  'application_approved',
  'application_rejected',
  'comment_added',
  'budget_reserved',
  'budget_booked',
  'protocol_finalized',
  'deadline_approaching',
  'deadline_passed',
] as const;

export type RecipientKind = 'group' | 'role' | 'applicant';

export interface Recipient {
  kind: RecipientKind;
  ref?: string | null;
}

export interface WebhookConfig {
  id: Uuid;
  name: string;
  url: string;
  events: EventName[];
  active: boolean;
}

/** Gremium role — a separate role set, distinct from the global roles. */
export interface GremiumRole {
  id: Uuid;
  gremiumId: Uuid;
  key: string;
  name: I18nMap;
  /** Forced role (board/manager/member) — present in every gremium, not deletable. */
  forced?: boolean;
  /** Granular meeting permissions (session.manage/vote.manage/vote.cast/protocol.write). */
  permissions?: string[];
}

/** Configurable granular gremium-role permissions. */
export const GREMIUM_PERMISSIONS = [
  'session.manage',
  'vote.manage',
  'vote.cast',
  'protocol.write',
] as const;

/** Kind of a named deadline policy. */
export type DeadlineKind =
  | 'absolute'
  | 'relative_submitted'
  | 'relative_changed'
  | 'recurring';

/** Named deadline policy (registry, referenced by the flow via `key`). */
export interface DeadlinePolicy {
  id: Uuid;
  key: string;
  label: I18nMap;
  kind: DeadlineKind;
  /** Only for `absolute`: a fixed date (editable per semester), ISO string. */
  absoluteAt?: string | null;
  /** Only for the relative variants: offset in days. */
  offsetDays?: number | null;
  /** Optional wall-clock anchor `"HH:MM"` (local time in `timezone`, DST-correct). */
  atTime?: string | null;
  /** IANA timezone for `atTime` (e.g. `Europe/Berlin`). */
  timezone?: string | null;
  /** Only for `recurring`: ordered list of `YYYY-MM-DD` dates (rolling window). */
  dates?: string[] | null;
}

/** Time-bounded gremium membership (term of office). */
export interface GremiumMembership {
  id: Uuid;
  principalId: Uuid;
  gremiumId: Uuid;
  gremiumRoleId: Uuid;
  validFrom: string | null;
  validUntil: string | null;
}

/** Append-only audit entry (`GET /admin/audit`). */
export interface AuditEntry {
  id: number;
  at: string;
  actor: string | null;
  /** Clear name of the actor, resolved by the backend. null = system or unknown. */
  actorName: string | null;
  action: string;
  targetType: string | null;
  targetId: string | null;
  /** Human-readable target label (application title, role name, …). null = unknown or
   *  deleted. */
  targetLabel?: string | null;
  data: Record<string, unknown>;
  /** UUID → clear name for entity references embedded in `data`, resolved by the
   *  backend. It holds only resolvable ids. The UI shows the raw UUID for the rest. */
  resolvedIds?: Record<string, string>;
  /** Revertible from the audit log (determined by the backend) — drives the
   *  "revert" button. The backend stays authoritative on click. */
  revertable?: boolean;
  hash: string;
  prevHash: string | null;
}

/** Cursor-paged audit response (keyset on `id`, newest first). */
export interface AuditPage {
  items: AuditEntry[];
  nextCursor: number | null;
  hasMore: boolean;
}

/** Distinct actor for the audit actor filter. */
export interface AuditActor {
  sub: string;
  name: string | null;
}

/**
 * A config snapshot (version sidebar). The list is append-only. Nobody can delete an
 * earlier version. `isCurrent` marks the active state.
 */
export interface ConfigRevision {
  id: Uuid;
  entityType: string;
  entityId: string;
  version: number;
  at: string;
  createdBy: string | null;
  createdByName: string | null;
  isCurrent: boolean;
}

/** Field diff of a config snapshot against its predecessor (wire form). */
export interface ConfigRevisionDiffWire {
  id: Uuid;
  entityType: string;
  entityId: string;
  version: number;
  prevVersion: number | null;
  diff: DataDiffWire;
}

/** Field diff of a config snapshot (FE view). `diff` is in array form for `@for`. */
export interface ConfigRevisionDiff {
  id: Uuid;
  entityType: string;
  entityId: string;
  version: number;
  prevVersion: number | null;
  diff: DataDiff | null;
}

/** Result of an audit-log revert. */
export interface AuditRevertResult {
  revertedAuditId: number;
  entityType: string;
  entityId: string;
}

/** Platform notification config (P admin.notifications). */
export interface NotificationSettings {
  taskReminderEnabled: boolean;
  /** Days without a status change before the platform sends a reminder (≥ 1). */
  taskReminderAfterDays: number;
  /** Then again every N days. 0 = only once per state visit. */
  taskReminderRepeatDays: number;
}

/** DSGVO erasure request (queue, P privacy.manage). */
export type ErasureSubjectType = 'applicant' | 'principal';
export type ErasureStatus = 'open' | 'executed' | 'rejected';

export interface ErasureRequest {
  id: Uuid;
  createdAt: string;
  subjectType: ErasureSubjectType;
  applicationId?: Uuid | null;
  principalId?: Uuid | null;
  email?: string | null;
  status: ErasureStatus;
  requestedBy?: string | null;
  handledBy?: string | null;
  handledAt?: string | null;
  reason?: string | null;
}

/** Platform-wide DSGVO config (global retention default, P privacy.manage). */
export interface PrivacySettings {
  defaultRetentionMonths: number;
}

// Branding / site-config

export type LogoSlot = 'wordmark' | 'imagemark' | 'favicon';

export interface BrandingAsset {
  /** Data URL or server-side asset URL of the image mark. */
  url: string;
  filename: string;
  mime: string;
  /** Size in bytes (for the mime/size hint display). */
  size: number;
}

export interface FooterLink {
  label: I18nMap;
  url: string;
}

export interface FooterColumn {
  label: I18nMap;
  links: FooterLink[];
}

export interface SiteFreetexts {
  /** Login hint, landing/welcome, support, email footer — each i18n. */
  loginHint: I18nMap;
  welcome: I18nMap;
  support: I18nMap;
  emailFooter: I18nMap;
  /** Info text below the application(-type) selection — Markdown, each i18n. */
  applyInfo?: I18nMap;
}

export interface Branding {
  /** Full app name (browser tab, header, home page). Empty ⇒ the i18n default. */
  appName?: string;
  /** Short app name (PWA icon/home screen). Empty ⇒ the default. */
  appShortName?: string;
  logos: Partial<Record<LogoSlot, BrandingAsset>>;
  footerColumns: FooterColumn[];
  copyright: I18nMap;
  legalLinks: FooterLink[];
  freetexts: SiteFreetexts;
}

/** Versioned site config: active version + editable draft. */
export interface SiteConfig {
  version: number;
  active: Branding;
  draft: Branding;
  /** true when `draft` carries unsaved/unactivated changes. */
  hasDraftChanges: boolean;
}

/**
 * Accepted logo MIME types + max size (UI hint + client guard).
 *
 * Security — img-only contract: the platform keeps branding logos site-wide as
 * `branding` JSON and renders them only through `<img src>`. It never injects a logo
 * inline into the DOM. `image/svg+xml` stays excluded on purpose. An SVG can carry
 * `<script>` or `on*` handlers. It would be a stored XSS vector for a future
 * inline-SVG consumer. Use raster formats only (PNG/JPEG/WebP/ICO). Any logo consumer
 * MUST stay on `<img src>`.
 */
export const LOGO_ACCEPT_MIME: readonly string[] = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/x-icon',
  'image/vnd.microsoft.icon',
] as const;
export const LOGO_MAX_SIZE_MB = 2;

/** Re-export so admin code imports only from `admin.models`. */
export type { FormFieldDef };
