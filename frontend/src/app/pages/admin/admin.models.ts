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
  /** CD variant the gremium renders its documents with. `null` = the renderer default. */
  cdVariantId: Uuid | null;
  defaultLang: string;
  allowVoteDelegation: boolean;
  /** Lead time in minutes before the meeting starts, for non-pool delegations.
   *  0 = until the start. */
  delegationLeadMinutes?: number;
  /** Allow delegation to users outside the gremium & substitute pool. */
  delegationAllowExternal?: boolean;
  /** Default quorum as a percent of eligible voters who must attend. null = none. */
  quorumPercent?: number | null;
  /** Number of members. Only the admin list (`GET /admin/gremien`) gives it. */
  memberCount?: number;
  /** Number of gremium roles, the forced roles included. Admin list only. */
  roleCount?: number;
}

/** Body for `POST /admin/gremien` (`GremiumCreate`). */
export interface GremiumCreateBody {
  name: string;
  slug: string;
  cdVariantId: Uuid | null;
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
  cdVariantId?: Uuid | null;
  defaultLang?: string;
  allowVoteDelegation?: boolean;
  delegationLeadMinutes?: number;
  delegationAllowExternal?: boolean;
  quorumPercent?: number | null;
}

// Corporate-design variants — mirror of `admin/cd_logos.py` and the CD schemas.
// A variant only controls the logos of a rendered document. It carries no color
// and no font.

/** Document shape a variant builds on. */
export type CdBaseVariant = 'report' | 'protocol';
export const CD_BASE_VARIANTS: readonly CdBaseVariant[] = ['report', 'protocol'] as const;

/** Where a logo appears: on the title page or in the page footer. */
export type CdLogoSlot = 'title' | 'footer';
export const CD_LOGO_SLOTS: readonly CdLogoSlot[] = ['title', 'footer'] as const;

/** Logo names that the render service ships (`VendoredLogoName`). They need no upload. */
export const VENDORED_LOGO_NAMES: readonly string[] = [
  'HSRT',
  'INF',
  'ASTA',
  'STUPA',
  'ECHO',
  'MAKERS',
  'MAKERS-RAlign',
  'MAKERS-Icon',
  'Skyline',
] as const;

/** Types the server accepts for an uploaded logo (`ALLOWED_CD_LOGO_MIME`). */
export const CD_LOGO_ACCEPT = 'image/png,image/jpeg,image/webp,image/svg+xml,application/pdf';
/** Size cap of an uploaded logo (`MAX_CD_LOGO_BYTES`). */
export const MAX_CD_LOGO_BYTES = 2 * 1024 * 1024;

/** Key pattern of a CD variant (`CD_VARIANT_KEY_PATTERN`). The key is a slug. */
export const CD_VARIANT_KEY_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const CD_VARIANT_KEY_MAX = 64;

/** One logo of a variant. Exactly one of `vendoredName` / `fileName` is set. */
export interface CdVariantLogo {
  id: Uuid;
  slot: CdLogoSlot;
  position: number;
  vendoredName?: string | null;
  fileName?: string | null;
  mime?: string | null;
  size?: number | null;
}

/** A CD variant with its logos, ordered by slot and position. */
export interface CdVariant {
  id: Uuid;
  key: string;
  name: string;
  baseVariant: CdBaseVariant;
  logos: CdVariantLogo[];
}

/** Slim option for the gremium dropdown — `GET /cd-variants`. */
export interface CdVariantOption {
  id: Uuid;
  key: string;
  name: string;
}

/** Body for `POST /admin/cd-variants`. */
export interface CdVariantCreateBody {
  key: string;
  name: string;
  baseVariant: CdBaseVariant;
}

/** Body for `PATCH /admin/cd-variants/{id}`. The key is immutable (409). */
export interface CdVariantUpdateBody {
  name?: string;
  baseVariant?: CdBaseVariant;
}

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

/**
 * OIDC group → global role (admin API `/admin/group-mappings`).
 *
 * A global role has no gremium scope. Gremium membership and gremium roles have
 * their own mappings, see {@link GremiumMembershipMapping} and
 * {@link GremiumRoleMapping}.
 */
export interface GroupMapping {
  id: Uuid;
  oidcGroup: string;
  roleId: Uuid;
}

/** Input to create or change a global group mapping. */
export interface GroupMappingBody {
  oidcGroup: string;
  roleId: Uuid;
}

/**
 * Role assignment (admin API `/role-assignments`, read-only).
 *
 * Only the bootstrap writes these rows: `admin` from the settings and the implicit
 * `member`. All other global roles come from the OIDC group mappings.
 */
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

/** OIDC principal (user) incl. its role assignments (admin API `/principals`). */
export interface AdminPrincipal {
  id: Uuid;
  sub: string;
  email?: string | null;
  displayName?: string | null;
  lastLogin?: string | null;
  active?: boolean;
  assignments: RoleAssignment[];
  /** The OIDC groups as of the last login. The group mappings read them. */
  oidcGroups: string[];
  /**
   * Account merge: set when an admin merged this (old) account into another one. The
   * account is then a locked reference: "zusammengeführt in <name>", no actions.
   */
  mergedIntoId?: Uuid | null;
  mergedIntoName?: string | null;
  mergedAt?: string | null;
}

/**
 * The areas of an account merge, in display order. Each one counts the rows that the
 * merge rewrites to the new account, the duplicates it combines, and the rows it removes.
 * Mirrors `MergeArea` in `backend/app/modules/admin/schemas.py`.
 */
export const MERGE_AREAS = [
  'applications',
  'versions',
  'timeline',
  'comments',
  'votes',
  'delegations',
  'substitutes',
  'attendance',
  'meetings',
  'budget',
  'config',
  'notifications',
  'roles',
  'privacy',
  'backups',
  'sessions',
  'memberships',
  'calendar',
] as const;
export type MergeArea = (typeof MERGE_AREAS)[number];

/** A real conflict that blocks a merge. Mirrors `MergeConflictKind` in the backend. */
export type MergeConflictKind =
  | 'ballot_same_vote'
  | 'delegation_same_meeting'
  | 'delegation_vote_twice'
  | 'delegation_chain'
  | 'attendance_differs'
  | 'erasure_open';

export interface MergeAreaCount {
  area: MergeArea;
  rewritten: number;
  combined: number;
  removed: number;
}

export interface MergeConflict {
  kind: MergeConflictKind;
  /** The vote or the meeting, never an id. Null when the kind names no object. */
  label: string | null;
}

/** One side of a merge: the old account (source) or the account that stays (target). */
export interface MergePrincipal {
  id: Uuid;
  displayName: string | null;
  email: string | null;
  lastLogin: string | null;
}

/** GET /admin/principals/{id}/merge-preview?targetId= */
export interface MergePreview {
  source: MergePrincipal;
  target: MergePrincipal;
  areas: MergeAreaCount[];
  conflicts: MergeConflict[];
  canMerge: boolean;
}

/** POST /admin/principals/{id}/merge */
export interface MergeResult {
  source: MergePrincipal;
  target: MergePrincipal;
  areas: MergeAreaCount[];
  mergedAt: string;
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
  /** Number of the active form version (`v7`). `null` while no version is active. */
  activeFormVersion?: number | null;
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

/** Coarse state of the most recent delivery of one webhook. */
export type WebhookDeliveryState = 'never' | 'pending' | 'sent' | 'dead';

/**
 * Delivery diagnostics of one webhook (`GET /admin/webhooks/delivery-status`).
 *
 * The backend reduces the newest `webhook_delivery` row to a coarse state plus a
 * coarse reason class. It sends no resolved IP, no host topology and no response
 * body, so an operator can diagnose a mistyped or internal target without a leak.
 */
export interface WebhookDeliveryStatus {
  webhookId: Uuid;
  lastState: WebhookDeliveryState;
  /** `delivered`, `in_progress`, `no_deliveries`, `rejected_by_target`,
   *  `target_server_error`, `transient_transport_error`, `unreachable_or_blocked`
   *  or `unknown`. */
  reasonClass: string;
  responseCode?: number | null;
  attempts: number;
  lastAt?: string | null;
}

/** Gremium role — a separate role set, distinct from the global roles. */
export interface GremiumRole {
  id: Uuid;
  gremiumId: Uuid;
  key: string;
  name: I18nMap;
  /** Forced role (`vorstand`, `manager`, `member`): present in every gremium, not deletable. */
  forced?: boolean;
  /** The gremium permissions of the role, a subset of {@link GREMIUM_PERMISSIONS}. */
  permissions?: string[];
}

/**
 * The fixed catalogue of gremium permissions (O7), in display order. It mirrors
 * `GREMIUM_PERMISSIONS` in `backend/app/modules/admin/gremium_roles.py`. The catalogue
 * is not configurable, so this list is the source of the role matrix and the role
 * dialog.
 */
export const GREMIUM_PERMISSIONS = [
  'session.manage',
  'vote.manage',
  'vote.cast',
  'protocol.write',
  'protocol.finalize',
] as const;

/** One key of the fixed gremium permission catalogue. */
export type GremiumPermission = (typeof GREMIUM_PERMISSIONS)[number];

/**
 * The keys of the forced gremium roles, in display order. Every gremium has them and
 * nobody can delete them. A member without a role mapping gets `member`.
 */
export const FORCED_GREMIUM_ROLE_KEYS = ['vorstand', 'manager', 'member'] as const;

/** The key of the forced role that every member without a role mapping gets. */
export const MEMBER_GREMIUM_ROLE_KEY = 'member';

/**
 * Sort the roles of one gremium for display: the forced roles first, in the order of
 * {@link FORCED_GREMIUM_ROLE_KEYS}, then the other roles by name.
 */
export function sortGremiumRoles(roles: readonly GremiumRole[], label: (r: GremiumRole) => string): GremiumRole[] {
  const rank = (r: GremiumRole): number => {
    const i = (FORCED_GREMIUM_ROLE_KEYS as readonly string[]).indexOf(r.key);
    return i < 0 ? FORCED_GREMIUM_ROLE_KEYS.length : i;
  };
  return [...roles].sort((a, b) => rank(a) - rank(b) || label(a).localeCompare(label(b)));
}

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

/**
 * One live OAuth grant (agent/MCP token pair) of any principal — the admin view of
 * `GET /admin/oauth-grants` (P `admin.users`).
 *
 * The server resolves the owner to a name, so the UI never renders an id.
 * `principalName` is `null` when the owner carries neither a display name nor an
 * email; the page then shows a localized placeholder. `principalId` exists for the
 * filter and for a deep link only, never for display. The item holds no token and no
 * token hash.
 */
export interface OAuthGrantAdmin {
  id: Uuid;
  principalId: Uuid;
  /** Display name, else email, else `null`. NEVER an id. */
  principalName: string | null;
  principalEmail: string | null;
  clientId: string;
  scope: string;
  createdAt: string;
  /** The server caps every lifetime, so a value is normal. The page shows `null` as a dash. */
  accessExpiresAt: string | null;
  /** The server caps every lifetime, so a value is normal. The page shows `null` as a dash. */
  refreshExpiresAt: string | null;
}

/** Query of the admin grant list: offset paging plus the owner filter. */
export interface OAuthGrantQuery {
  limit?: number;
  offset?: number;
  principalId?: Uuid | null;
}

/**
 * Gremium membership (read-only).
 *
 * The backend derives it from the OIDC groups of the principal: the membership
 * mappings give the membership, the gremium role mappings give the role. It syncs
 * at each login and after each mapping change.
 */
export interface GremiumMembership {
  id: Uuid;
  principalId: Uuid;
  gremiumId: Uuid;
  gremiumRoleId: Uuid;
  /** The display name of the member. `null` when the IdP gives none. */
  displayName?: string | null;
  /** The e-mail address of the member. `null` when the IdP gives none. */
  email?: string | null;
  /**
   * The principal is active and the membership is valid now, the rule of the member
   * count in the gremien list. A missing value counts as active.
   */
  active?: boolean;
}

/** True when a membership counts as a current member (see `GremiumMembership.active`). */
export function isActiveMembership(m: GremiumMembership): boolean {
  return m.active !== false;
}

/**
 * OIDC group → membership in one gremium (`/admin/gremium-membership-mappings`).
 *
 * Each person in the group becomes a member of the gremium, with the default
 * gremium role `member`. Only this mapping gives a membership.
 */
export interface GremiumMembershipMapping {
  id: Uuid;
  gremiumId: Uuid;
  oidcGroup: string;
}

/** Input to create or change a membership mapping. */
export interface GremiumMembershipMappingBody {
  oidcGroup: string;
  gremiumId: Uuid;
}

/**
 * OIDC group → role of one gremium (`/admin/gremium-role-mappings`).
 *
 * The role applies only to persons who are members of that gremium through a
 * {@link GremiumMembershipMapping}. It never gives a membership. `gremiumId` is the
 * gremium of the role and is read-only.
 */
export interface GremiumRoleMapping {
  id: Uuid;
  gremiumId: Uuid;
  gremiumRoleId: Uuid;
  oidcGroup: string;
}

/** Input to create or change a gremium role mapping. The role sets the gremium. */
export interface GremiumRoleMappingBody {
  oidcGroup: string;
  gremiumRoleId: Uuid;
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

/** What started a stored chain check: the nightly job, a person, or a restore. */
export type AuditVerificationTrigger = 'cron' | 'manual' | 'restore';

/** Why a chain check failed. */
export type AuditChainBreak = 'prev_hash_mismatch' | 'hash_mismatch';

/**
 * A stored check of the audit hash chain (`GET /admin/audit/verify/latest`,
 * `POST /admin/audit/verify`). `brokenAt` and `reason` name the first break when
 * `valid` is false.
 */
export interface AuditVerification {
  id: Uuid;
  startedAt: string;
  finishedAt: string | null;
  valid: boolean;
  /** Number of entries the check read. */
  checked: number;
  brokenAt: number | null;
  reason: AuditChainBreak | null;
  trigger: AuditVerificationTrigger;
  triggeredBy: string | null;
}

/** A live check of the chain that the server does not store (`GET /admin/audit/verify`). */
export interface AuditChainCheck {
  valid: boolean;
  checked: number;
  brokenAt: number | null;
  reason: string | null;
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

/**
 * Settings for applications without an account (Z1, P admin.deadlines):
 * `GET/PUT /admin/guest-settings`.
 */
export interface GuestSettings {
  /** Hours until the platform discards an unconfirmed guest application (1 to 720). */
  confirmTtlHours: number;
  /** Lifetime of a new personal link in days (1 to 3650). `null` = no expiry. */
  linkTtlDays: number | null;
  updatedAt?: string | null;
  updatedBy?: string | null;
}

/** Upper bound of {@link GuestSettings.confirmTtlHours} (`MAX_CONFIRM_TTL_HOURS`). */
export const MAX_CONFIRM_TTL_HOURS = 720;
/** Upper bound of {@link GuestSettings.linkTtlDays} (`MAX_LINK_TTL_DAYS`). */
export const MAX_LINK_TTL_DAYS = 3650;

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

// Backups (P backup.manage)

/** Why the archive exists. `preRestore` is the safety copy a restore takes first. */
export type BackupKind = 'manual' | 'scheduled' | 'pre_restore' | 'imported';

/** Job state of the archive build. The page polls while it is not terminal. */
export type BackupStatus = 'pending' | 'running' | 'done' | 'failed';

/**
 * One whole-platform archive: a `pg_dump` plus a mirror of the attachment bucket,
 * age-encrypted in its own bucket. The row is metadata only; the archive itself never
 * passes through the browser except as a signed download.
 */
export interface Backup {
  id: Uuid;
  kind: BackupKind;
  status: BackupStatus;
  createdAt: string;
  finishedAt?: string | null;
  /** OIDC `sub` of whoever started it. Null for the nightly job. */
  createdBy?: string | null;
  sizeBytes?: number | null;
  objectCount?: number | null;
  checksum?: string | null;
  note?: string | null;
  appVersion?: string | null;
  schemaRevision?: string | null;
  /** A pinned archive is never pruned by retention and cannot be deleted. */
  pinned: boolean;
  /** Short failure code. Never carries a path. */
  error?: string | null;
}

/** The catalogue plus what this installation can actually do. */
export interface BackupList {
  items: Backup[];
  /** False without an age recipient: creating is off and the page says why. */
  enabled: boolean;
  /** False without the private key: the platform cannot read its own archives. */
  restoreEnabled: boolean;
  retentionCount: number;
}

/** The literal a restore has to carry. It is a machine token, never translated. */
export const BACKUP_RESTORE_CONFIRMATION = 'RESTORE';

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
  /** Show the Gravatar images of the avatars. Missing (an older config) = on. */
  gravatarEnabled?: boolean;
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

/**
 * Pattern for the key of a new role (global role and gremium role). It mirrors
 * `ROLE_KEY_PATTERN` in `backend/app/modules/admin/schemas.py`. The server refuses
 * a key that does not match with 422. A key never changes after the create.
 */
export const ROLE_KEY_PATTERN = /^[a-z][a-z0-9_]*$/;
