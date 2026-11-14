/**
 * Admin config DTOs — mirror of the admin API and the config schemas. camelCase like
 * the backend `_CamelModel`. The backend OpenAPI stays the source of truth.
 *
 * In mock mode (`USE_MOCK_API`) an in-memory store provides data so the UIs are
 * developable and testable. Branding/site-config uses the local `/api/admin/site-config`
 * path, which is not part of the API spec.
 */
import type { FeatureKey } from '@core/features/feature.service';
import type {
  DataDiff,
  DataDiffWire,
  FormFieldDef,
  I18nMap,
  Uuid,
} from '@core/api/models';

/** State kind in the global flow: only normal + vote. */
export type StateKind = 'normal' | 'vote';

/** Per-state config depending on `kind`. Empty object for `normal`. */
/** Where a vote state takes its gremium from, besides a fixed `gremiumId`. */
export type GremiumSource = 'budget';

export interface StateConfig {
  /** vote: the fixed gremium that votes. Exactly one of `gremiumId` and `gremiumSource`. */
  readonly gremiumId?: string;
  /**
   * vote: `budget` takes the deciding gremium of the cost center of the application when
   * the application enters the state (`decisionGremiumId` of the node or an ancestor).
   */
  readonly gremiumSource?: GremiumSource;
}

export interface StateDef {
  readonly key: string;
  readonly label: I18nMap;
  /** Display color of the state badge (hex), optional. */
  readonly color?: string | null;
  readonly editAllowed?: boolean;
  readonly isInitial?: boolean;
  /** Terminal state: terminal applications are subject to retention/anonymization. */
  readonly isTerminal?: boolean;
  /** An Antrag in this state counts as approved (spec 000571). Never with `isDenied`. */
  readonly isApproved?: boolean;
  /** An Antrag in this state counts as denied (spec 000571). Never on a vote state. */
  readonly isDenied?: boolean;
  /** State kind. Absent ⇒ `normal`. */
  readonly kind?: StateKind | null;
  /** Kind-specific configuration. */
  readonly config?: StateConfig | null;
}

/** Result branch of a vote state: pass/fail. */
export type TransitionBranch = 'pass' | 'fail';

export interface TransitionDef {
  readonly from: string;
  readonly to: string;
  readonly label?: I18nMap | null;
  /** Optional color: tints the arrow in the editor + the decision button in the application. */
  readonly color?: string | null;
  readonly guard?: Guard | null;
  readonly actions?: readonly ActionDef[];
  readonly order?: number | null;
  /** Automatic transition: fires without user action as soon as the guard holds. */
  readonly automatic?: boolean;
  /** Result branch for vote states: pass/fail. */
  readonly branch?: TransitionBranch | null;
  /** "Requires action": counts as an open task in the tasks tab.
   *  Absent ⇒ `true`. `false` = a purely optional action. */
  readonly requiresAction?: boolean;
}

/** Visual node group. Only the editor renders it and the engine ignores it. On the
 *  canvas a group is always ONE labeled box. Its content opens through drill-down
 *  (breadcrumbs). Groups nest through `groupIds`. A state or group sits in at most
 *  one parent. */
export interface FlowGroup {
  readonly id: string;
  readonly name: string;
  readonly stateKeys: readonly string[];
  /** Directly contained sub-groups (nesting). */
  readonly groupIds?: readonly string[];
  readonly color?: string | null;
}

/** Optional editor layout (node positions + groups). The graph stores it. */
export interface FlowLayout {
  readonly positions?: Record<string, { readonly x: number; readonly y: number }>;
  readonly groups?: readonly FlowGroup[];
}

export interface FlowGraph {
  readonly states: readonly StateDef[];
  readonly transitions: readonly TransitionDef[];
  readonly layout?: FlowLayout | null;
}

/**
 * Comparison operators of the `compare` guard (type-dependent at runtime). The guard types
 * mirror the backend whitelist in `shared/guards.py`.
 */
export type CompareOp = '==' | '!=' | '<' | '<=' | '>' | '>=' | 'in';
export const COMPARE_OPS: readonly CompareOp[] = ['==', '!=', '<', '<=', '>', '>=', 'in'] as const;

/** Condition operators (on automatic + manual transitions). */
export type GuardConditionOp =
  | 'applicantRoleIs'
  | 'applicantCommitteeIs'
  | 'applicationTypeIs'
  | 'attachmentPresent'
  | 'budgetIs'
  | 'budgetFitsApplication'
  | 'budgetHasDecisionGremium'
  | 'hasField'
  | 'compare';
/** Actor gates — only on manual transitions. */
export type GuardActorOp = 'roleIs' | 'isInCommittee' | 'isInVoteGremium' | 'actorIsApplicant';
export type GuardLeafOperator = GuardConditionOp | GuardActorOp;
export type GuardCombinator = 'and' | 'or' | 'not';

/** A single guard node (exactly one operator, like `validate_guard`). */
export type Guard = Record<string, unknown>;

export const GUARD_CONDITION_OPERATORS: readonly GuardConditionOp[] = [
  'applicantRoleIs',
  'applicantCommitteeIs',
  'applicationTypeIs',
  'attachmentPresent',
  'budgetIs',
  'budgetFitsApplication',
  'budgetHasDecisionGremium',
  'hasField',
  'compare',
] as const;
export const GUARD_ACTOR_OPERATORS: readonly GuardActorOp[] = [
  'roleIs',
  'isInCommittee',
  'isInVoteGremium',
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
  | 'assignBudgetFromField'
  | 'assignBudgetFromApplicantGremium'
  | 'assignBudgetFromMap';
export const ACTION_TYPES: readonly ActionType[] = [
  'webhook',
  'notify',
  'addToNextSession',
  'assignBudget',
  'assignBudgetFromField',
  'assignBudgetFromApplicantGremium',
  'assignBudgetFromMap',
] as const;

/**
 * The actions that set the cost center. None of them may sit on a transition into a vote
 * state with `gremiumSource: 'budget'`: the state takes its gremium on entry, before the
 * action runs.
 */
export const ASSIGN_BUDGET_ACTIONS: readonly ActionType[] = [
  'assignBudget',
  'assignBudgetFromField',
  'assignBudgetFromApplicantGremium',
  'assignBudgetFromMap',
] as const;

/** Bool-valued guard operators. Mirrors `_BOOL_VALUE_OPERATORS` of the backend. */
export const GUARD_BOOL_OPERATORS: readonly GuardLeafOperator[] = [
  'budgetFitsApplication',
  'budgetHasDecisionGremium',
  'actorIsApplicant',
  'attachmentPresent',
  'isInVoteGremium',
] as const;

/**
 * Recipient kind of a `notify` action. `voteGremium` is the gremium that decides the
 * current vote; `budgetGremium` is the deciding gremium of the cost center. Both take
 * no `ref`.
 */
export type NotifyRecipientKind =
  | 'gremium'
  | 'role'
  | 'applicant'
  | 'email'
  | 'voteGremium'
  | 'budgetGremium';
export const NOTIFY_RECIPIENT_KINDS: readonly NotifyRecipientKind[] = [
  'gremium',
  'role',
  'applicant',
  'email',
  'voteGremium',
  'budgetGremium',
] as const;
export interface NotifyRecipient {
  readonly kind: NotifyRecipientKind;
  readonly ref?: string;
}

export interface ActionDef {
  readonly type: ActionType;
  readonly [param: string]: unknown;
}

/** A gremium. The organization and RBAC types mirror `admin/models.py`. */
export interface Gremium {
  readonly id: Uuid;
  readonly name: string;
  readonly slug: string;
  /** CD variant the gremium renders its documents with. `null` = the renderer default. */
  readonly cdVariantId: Uuid | null;
  readonly defaultLang: string;
  readonly allowVoteDelegation: boolean;
  /** Lead time in minutes before the meeting starts, for non-pool delegations.
   *  0 = until the start. */
  readonly delegationLeadMinutes?: number;
  /** Allow delegation to users outside the gremium & substitute pool. */
  readonly delegationAllowExternal?: boolean;
  /** Default quorum as a percent of eligible voters who must attend. null = none. */
  readonly quorumPercent?: number | null;
  /** Number of members. Only the admin list (`GET /admin/committees`) gives it. */
  readonly memberCount?: number;
  /** Number of gremium roles, the forced roles included. Admin list only. */
  readonly roleCount?: number;
  /** The final protocols of the gremium show on the public protocol page. */
  readonly protocolsPublic?: boolean;
}

/** `GET /admin/committees/{id}/public-preview`: what a switch to "public" publishes. */
export interface GremiumPublicPreview {
  /** The final protocols that are not held back. */
  readonly finalCount: number;
  /** Of them, the protocols without a public version yet (a job makes it). */
  readonly missingCount: number;
}

/** Body for `POST /admin/committees` (`GremiumCreate`). */
export interface GremiumCreateBody {
  readonly name: string;
  readonly slug: string;
  readonly cdVariantId: Uuid | null;
  readonly defaultLang: string;
  readonly allowVoteDelegation?: boolean;
  readonly delegationLeadMinutes?: number;
  readonly delegationAllowExternal?: boolean;
  readonly quorumPercent?: number | null;
  readonly protocolsPublic?: boolean;
}

/** Body for `PATCH /admin/committees/{id}` (`GremiumUpdate`) — all fields optional. */
export interface GremiumUpdateBody {
  readonly name?: string;
  readonly slug?: string;
  readonly cdVariantId?: Uuid | null;
  readonly defaultLang?: string;
  readonly allowVoteDelegation?: boolean;
  readonly delegationLeadMinutes?: number;
  readonly delegationAllowExternal?: boolean;
  readonly quorumPercent?: number | null;
  readonly protocolsPublic?: boolean;
}

/**
 * Document shape a corporate-design variant builds on. The variant types mirror
 * `admin/cd_logos.py` and the CD schemas. A variant only controls the logos of a rendered
 * document. It carries no color and no font.
 */

/**
 * Where a logo appears: on the title page or in the page footer of a PDF, or as the
 * square 1:1 logo that the app shows for a Gremium (`square`, at most one per variant).
 */
export type CdLogoSlot = 'title' | 'footer' | 'square';
/** The order of the slot choice in the "add a logo" dialog. */
export const CD_LOGO_SLOTS: readonly CdLogoSlot[] = ['title', 'footer', 'square'] as const;
/** The order of the logo rows of a variant: the square logo first. */
export const CD_LOGO_LIST_ORDER: readonly CdLogoSlot[] = ['square', 'title', 'footer'] as const;

/** Types the server accepts for a title or footer logo (`ALLOWED_CD_LOGO_MIME`). */
export const CD_LOGO_ACCEPT = 'image/png,image/jpeg,image/webp,image/svg+xml,application/pdf';
/**
 * Types the server accepts for the square logo (`ALLOWED_SQUARE_LOGO_MIME`). The browser
 * shows it inline, so no SVG.
 */
export const CD_SQUARE_LOGO_ACCEPT = 'image/png,image/jpeg,image/webp';
/** Size cap of an uploaded logo (`MAX_CD_LOGO_BYTES`). */
export const MAX_CD_LOGO_BYTES = 2 * 1024 * 1024;
/** The shortest edge of a square logo in pixels (`SQUARE_LOGO_MIN_PX`). */
export const SQUARE_LOGO_MIN_PX = 256;
/** The longest edge of a square logo in pixels (`SQUARE_LOGO_MAX_PX`). */
export const SQUARE_LOGO_MAX_PX = 4096;
/** How far width and height may differ, as a part of the longer edge (`SQUARE_LOGO_TOLERANCE`). */
export const SQUARE_LOGO_TOLERANCE = 0.01;

/** Key pattern of a CD variant (`CD_VARIANT_KEY_PATTERN`). The key is a slug. */
export const CD_VARIANT_KEY_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const CD_VARIANT_KEY_MAX = 64;

/**
 * One logo of a variant. Exactly one of `vendoredName` / `fileName` is set. A vendored
 * logo is a row from before the upload-only release; the worker turns it into an upload
 * at its next start, so the page only shows it.
 */
export interface CdVariantLogo {
  readonly id: Uuid;
  readonly slot: CdLogoSlot;
  readonly position: number;
  readonly vendoredName?: string | null;
  readonly fileName?: string | null;
  readonly mime?: string | null;
  readonly size?: number | null;
}

/** A CD variant with its logos, ordered by slot and position. */
export interface CdVariant {
  readonly id: Uuid;
  readonly key: string;
  readonly name: string;
  readonly logos: readonly CdVariantLogo[];
}

/** Slim option for the gremium dropdown — `GET /cd-variants`. */
export interface CdVariantOption {
  readonly id: Uuid;
  readonly key: string;
  readonly name: string;
}

/** Body for `POST /admin/cd-variants`. */
export interface CdVariantCreateBody {
  readonly key: string;
  readonly name: string;
}

/** Body for `PATCH /admin/cd-variants/{id}`. The key is immutable (409). */
export interface CdVariantUpdateBody {
  readonly name?: string;
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
  readonly id: Uuid;
  readonly key: string;
  readonly label: I18nMap;
  readonly permissions: readonly string[];
}

/** Mail template (admin API `/admin/mail-templates`): i18n subject/body/HTML. */
export interface MailTemplate {
  /** Builtins (not yet overridden) have no DB id. */
  readonly id: Uuid | null;
  readonly key: string;
  readonly subjectI18n: I18nMap;
  readonly bodyI18n: I18nMap;
  readonly bodyHtmlI18n: I18nMap;
  readonly placeholders: Record<string, string>;
  /** 'override' = from the DB. 'builtin' = the unchanged catalog default. */
  readonly source: 'override' | 'builtin';
}

/** Create/update an override by key (catalog merge). */
export interface MailTemplateUpsertBody {
  readonly key: string;
  readonly subjectI18n: I18nMap;
  readonly bodyI18n: I18nMap;
  readonly bodyHtmlI18n: I18nMap;
}

/** Preview from the editor draft (no id). */
export interface MailPreviewPayload {
  readonly subjectI18n: I18nMap;
  readonly bodyI18n: I18nMap;
  readonly bodyHtmlI18n: I18nMap;
  readonly lang: string;
  readonly context: Record<string, unknown>;
}

/** Rendered preview of a template. */
export interface MailPreview {
  readonly subject: string;
  readonly text: string;
  readonly html?: string | null;
  readonly lang: string;
}

/**
 * OIDC group → global role (admin API `/admin/group-mappings`).
 *
 * A global role has no gremium scope. Gremium membership and gremium roles have
 * their own mappings, see {@link GremiumMembershipMapping} and
 * {@link GremiumRoleMapping}.
 */
export interface GroupMapping {
  readonly id: Uuid;
  readonly oidcGroup: string;
  readonly roleId: Uuid;
}

/** Input to create or change a global group mapping. */
export interface GroupMappingBody {
  readonly oidcGroup: string;
  readonly roleId: Uuid;
}

/**
 * Role assignment (admin API `/role-assignments`, read-only).
 *
 * Only the bootstrap writes these rows: `admin` from the settings and the implicit
 * `member`. All other global roles come from the OIDC group mappings.
 */
export interface RoleAssignment {
  readonly id: Uuid;
  readonly principalId: Uuid;
  readonly roleId: Uuid;
  readonly grantedBy?: string | null;
}

/** OIDC principal (user) incl. its role assignments (admin API `/principals`). */
export interface AdminPrincipal {
  readonly id: Uuid;
  readonly sub: string;
  readonly email?: string | null;
  readonly displayName?: string | null;
  readonly lastLogin?: string | null;
  readonly active?: boolean;
  readonly assignments: readonly RoleAssignment[];
  /** The OIDC groups as of the last login. The group mappings read them. */
  readonly oidcGroups: readonly string[];
  /**
   * Account merge: set when an admin merged this (old) account into another one. The
   * account is then a locked reference: "zusammengeführt in <name>", no actions.
   */
  readonly mergedIntoId?: Uuid | null;
  readonly mergedIntoName?: string | null;
  readonly mergedAt?: string | null;
  /**
   * Revoke rights: the person still has something that "Rechte entziehen" can take
   * away (an OIDC group, a membership, a role, a pool entry or a delegation).
   */
  readonly hasAccess?: boolean;
}

/**
 * The filters of `GET /admin/principals`. `lastLoginBefore` (ISO date) keeps the
 * people whose last login is before that day; `includeNever` adds the people who never
 * logged in (alone: only those); `hasGroups` keeps the people with or without OIDC groups.
 */
export interface PrincipalFilters {
  readonly lastLoginBefore?: string | null;
  readonly includeNever?: boolean;
  readonly hasGroups?: boolean | null;
}

/** The person of a revoke: the header of the dialog. */
export interface RevokePrincipal {
  readonly id: Uuid;
  readonly displayName: string | null;
  readonly email: string | null;
  readonly lastLogin: string | null;
  readonly active: boolean;
}

/** A global role assignment. `grantedBy` is a name or `bootstrap`, never a `sub`. */
export interface RevokeAssignment {
  readonly id: Uuid;
  readonly roleId: Uuid;
  readonly roleKey: string;
  readonly roleLabel: I18nMap;
  readonly grantedBy: string | null;
  /** The bootstrap `admin` of a configured bootstrap admin: it comes back by itself. */
  readonly returnsAutomatically?: boolean;
}

/** A pool entry of the person: as substitute (for a member or the whole Gremium) or as member. */
export interface RevokePoolEntry {
  readonly id: Uuid;
  readonly asSubstitute: boolean;
  readonly gremiumWide: boolean;
  readonly memberName: string | null;
  readonly substituteName: string | null;
}

/** A delegation of the person in a planned or a live meeting. */
export interface RevokeDelegation {
  readonly id: Uuid;
  readonly meetingId: Uuid;
  readonly meetingTitle: string;
  readonly meetingDate: string | null;
  readonly asDelegator: boolean;
  readonly otherName: string | null;
  readonly voting: boolean;
}

/** Everything that ties the person to one Gremium. A revoke clears all of it. */
export interface RevokeGremium {
  readonly gremiumId: Uuid;
  readonly name: string;
  readonly membership: {
    readonly roleKey: string;
    readonly roleLabel: I18nMap;
    readonly groups: readonly string[];
  } | null;
  readonly groups: readonly string[];
  readonly poolEntries: readonly RevokePoolEntry[];
  readonly plannedDelegations: readonly RevokeDelegation[];
  readonly liveDelegations: readonly RevokeDelegation[];
  readonly openTasks: number;
}

/** A global role of the person and its origin. */
export interface RevokeGlobalRole {
  readonly roleId: Uuid;
  readonly roleKey: string;
  readonly roleLabel: I18nMap;
  readonly groups: readonly string[];
  readonly assignments: readonly RevokeAssignment[];
}

/** One SSO group of the person and every entry of the preview it leads to. */
export interface RevokeGroup {
  readonly group: string;
  readonly gremiumIds: readonly Uuid[];
  readonly globalRoleIds: readonly Uuid[];
}

/** GET /admin/principals/{id}/revoke-preview */
export interface RevokePreview {
  readonly principal: RevokePrincipal;
  readonly gremien: readonly RevokeGremium[];
  readonly globalRoles: readonly RevokeGlobalRole[];
  readonly groups: readonly RevokeGroup[];
  readonly isSelf: boolean;
}

/** Body of POST /admin/principals/{id}/revoke */
export interface RevokeRequest {
  readonly gremiumIds: readonly Uuid[];
  readonly globalRoleIds: readonly Uuid[];
  readonly deactivate: boolean;
}

/** POST /admin/principals/{id}/revoke */
export interface RevokeResult {
  readonly gremiumIds: readonly Uuid[];
  readonly globalRoleIds: readonly Uuid[];
  readonly removedGroups: readonly string[];
  readonly deletedAssignments: number;
  readonly deletedPoolEntries: number;
  readonly revokedDelegations: number;
  readonly keptLiveDelegations: number;
  readonly deactivated: boolean;
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
  'tickets',
  'todos',
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
  readonly area: MergeArea;
  readonly rewritten: number;
  readonly combined: number;
  readonly removed: number;
}

export interface MergeConflict {
  readonly kind: MergeConflictKind;
  /** The vote or the meeting, never an id. Null when the kind names no object. */
  readonly label: string | null;
}

/** One side of a merge: the old account (source) or the account that stays (target). */
export interface MergePrincipal {
  readonly id: Uuid;
  readonly displayName: string | null;
  readonly email: string | null;
  readonly lastLogin: string | null;
}

/**
 * A right of the old account that the target lacks. `key` is a permission key, or
 * `admin` for the admin role (every right); `gremium` names the gremium of a gremium
 * right.
 */
export interface MergePermission {
  readonly key: string;
  readonly gremium?: string | null;
}

/** GET /admin/principals/{id}/merge-preview?targetId= */
export interface MergePreview {
  readonly source: MergePrincipal;
  readonly target: MergePrincipal;
  readonly areas: readonly MergeAreaCount[];
  readonly conflicts: readonly MergeConflict[];
  /**
   * The rights of the old account that the target lacks. The merge moves no right, but
   * it moves ownership, so they block it unless the admin holds them all
   * (`actorHoldsExtra`).
   */
  readonly extraPermissions?: readonly MergePermission[];
  readonly actorHoldsExtra?: boolean;
  readonly canMerge: boolean;
}

/** POST /admin/principals/{id}/merge */
export interface MergeResult {
  readonly source: MergePrincipal;
  readonly target: MergePrincipal;
  readonly areas: readonly MergeAreaCount[];
  readonly mergedAt: string;
}

/** Comparison-offers rule of an application type. */
export interface ComparisonOffers {
  readonly required: boolean;
  readonly minCount: number;
  readonly thresholdAmount?: string | null;
  readonly as?: 'file' | 'field' | 'both';
}

/**
 * Application type (form) as the forms builder edit view. It mirrors the admin API type
 * `ApplicationTypeOut`. `name` is the i18n map that holds the form title.
 */
export interface ApplicationTypeFull {
  readonly id: Uuid;
  readonly name: I18nMap;
  readonly gremiumId?: Uuid | null;
  readonly hasBudget: boolean;
  /** The Antrag PDF ends with the signature section (spec 000888). */
  readonly pdfSignatures?: boolean;
  readonly comparisonOffers?: ComparisonOffers | null;
  /** DSGVO retention in months. null = the global default. */
  readonly retentionMonths?: number | null;
  readonly activeFormVersionId?: Uuid | null;
  /** Number of the active form version (`v7`). `null` while no version is active. */
  readonly activeFormVersion?: number | null;
}

/** Body for `POST /admin/application-types` — create an application type/form. */
export interface ApplicationTypeCreateBody {
  readonly key: string;
  readonly name: I18nMap;
  readonly gremiumId?: Uuid | null;
  readonly hasBudget?: boolean;
}

/** Body for `PATCH /admin/application-types/{id}` — title/gremium/budget. */
export interface ApplicationTypeUpdateBody {
  readonly name?: I18nMap;
  readonly gremiumId?: Uuid | null;
  readonly hasBudget?: boolean;
  readonly pdfSignatures?: boolean;
  readonly comparisonOffers?: ComparisonOffers | null;
}

/**
 * A type's current form version for editing — raw fields + description (forms editor).
 * For a freshly created type `fields` is empty.
 */
export interface FormDraft {
  readonly applicationTypeId: Uuid;
  readonly formVersionId?: Uuid | null;
  readonly version?: number | null;
  readonly active?: boolean;
  readonly description?: I18nMap | null;
  readonly fields: readonly FormFieldDef[];
}

export type FormStatus = 'active' | 'draft' | 'inactive';

/**
 * Overview row of active forms: display name, owning gremium, status and active form
 * version. The row aggregates application type and form version. Mock mode seeds it.
 */
export interface FormOverviewItem {
  readonly id: Uuid;
  readonly name: I18nMap;
  readonly gremiumId?: Uuid | null;
  readonly status: FormStatus;
  readonly version: number;
}

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
  | 'protocol_finalized';

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
] as const;

export type RecipientKind = 'group' | 'role' | 'applicant';

export interface WebhookConfig {
  readonly id: Uuid;
  readonly name: string;
  readonly url: string;
  readonly active: boolean;
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
  readonly webhookId: Uuid;
  readonly lastState: WebhookDeliveryState;
  /** `delivered`, `in_progress`, `no_deliveries`, `rejected_by_target`,
   *  `target_server_error`, `transient_transport_error`, `unreachable_or_blocked`
   *  or `unknown`. */
  readonly reasonClass: string;
  readonly responseCode?: number | null;
  readonly attempts: number;
  readonly lastAt?: string | null;
}

/** Gremium role — a separate role set, distinct from the global roles. */
export interface GremiumRole {
  readonly id: Uuid;
  readonly gremiumId: Uuid;
  readonly key: string;
  readonly name: I18nMap;
  /** Forced role (`vorstand`, `manager`, `member`): present in every gremium, not deletable. */
  readonly forced?: boolean;
  /** The gremium permissions of the role, a subset of {@link GREMIUM_PERMISSIONS}. */
  readonly permissions?: readonly string[];
}

/**
 * The fixed catalogue of gremium permissions, in display order. It mirrors
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
export function sortGremiumRoles(
  roles: readonly GremiumRole[],
  label: (r: GremiumRole) => string,
): readonly GremiumRole[] {
  const rank = (r: GremiumRole): number => {
    const i = (FORCED_GREMIUM_ROLE_KEYS as readonly string[]).indexOf(r.key);
    return i < 0 ? FORCED_GREMIUM_ROLE_KEYS.length : i;
  };
  return [...roles].sort((a, b) => rank(a) - rank(b) || label(a).localeCompare(label(b)));
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
  readonly id: Uuid;
  readonly principalId: Uuid;
  /** Display name, else email, else `null`. NEVER an id. */
  readonly principalName: string | null;
  readonly principalEmail: string | null;
  readonly clientId: string;
  readonly scope: string;
  readonly createdAt: string;
  /** The server caps every lifetime, so a value is normal. The page shows `null` as a dash. */
  readonly accessExpiresAt: string | null;
  /** The server caps every lifetime, so a value is normal. The page shows `null` as a dash. */
  readonly refreshExpiresAt: string | null;
}

/** Query of the admin grant list: offset paging plus the owner filter. */
export interface OAuthGrantQuery {
  readonly limit?: number;
  readonly offset?: number;
  readonly principalId?: Uuid | null;
}

/**
 * Gremium membership (read-only).
 *
 * The backend derives it from the OIDC groups of the principal: the membership
 * mappings give the membership, the gremium role mappings give the role. It syncs
 * at each login and after each mapping change.
 */
export interface GremiumMembership {
  readonly id: Uuid;
  readonly principalId: Uuid;
  readonly gremiumId: Uuid;
  readonly gremiumRoleId: Uuid;
  /** The display name of the member. `null` when the IdP gives none. */
  readonly displayName?: string | null;
  /** The e-mail address of the member. `null` when the IdP gives none. */
  readonly email?: string | null;
  /**
   * The principal is active and the membership is valid now, the rule of the member
   * count in the gremien list. A missing value counts as active.
   */
  readonly active?: boolean;
}

/** True when a membership counts as a current member (see `GremiumMembership.active`). */
export function isActiveMembership(m: GremiumMembership): boolean {
  return m.active !== false;
}

/**
 * OIDC group → membership in one gremium (`/admin/committee-membership-mappings`).
 *
 * Each person in the group becomes a member of the gremium, with the default
 * gremium role `member`. Only this mapping gives a membership.
 */
export interface GremiumMembershipMapping {
  readonly id: Uuid;
  readonly gremiumId: Uuid;
  readonly oidcGroup: string;
}

/** Input to create or change a membership mapping. */
export interface GremiumMembershipMappingBody {
  readonly oidcGroup: string;
  readonly gremiumId: Uuid;
}

/**
 * OIDC group → role of one gremium (`/admin/committee-role-mappings`).
 *
 * The role applies only to persons who are members of that gremium through a
 * {@link GremiumMembershipMapping}. It never gives a membership. `gremiumId` is the
 * gremium of the role and is read-only.
 */
export interface GremiumRoleMapping {
  readonly id: Uuid;
  readonly gremiumId: Uuid;
  readonly gremiumRoleId: Uuid;
  readonly oidcGroup: string;
}

/** Input to create or change a gremium role mapping. The role sets the gremium. */
export interface GremiumRoleMappingBody {
  readonly oidcGroup: string;
  readonly gremiumRoleId: Uuid;
}

/** Append-only audit entry (`GET /admin/audit`). */
export interface AuditEntry {
  readonly id: number;
  readonly at: string;
  readonly actor: string | null;
  /** Clear name of the actor, resolved by the backend. null = system or unknown. */
  readonly actorName: string | null;
  readonly action: string;
  readonly targetType: string | null;
  readonly targetId: string | null;
  /** Human-readable target label (application title, role name, …). null = unknown or
   *  deleted. */
  readonly targetLabel?: string | null;
  readonly data: Record<string, unknown>;
  /** UUID → clear name for entity references embedded in `data`, resolved by the
   *  backend. It holds only resolvable ids. The UI shows the raw UUID for the rest. */
  readonly resolvedIds?: Record<string, string>;
  /** Revertible from the audit log (determined by the backend) — drives the
   *  "revert" button. The backend stays authoritative on click. */
  readonly revertable?: boolean;
  readonly hash: string;
  readonly prevHash: string | null;
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
  readonly id: Uuid;
  readonly startedAt: string;
  readonly finishedAt: string | null;
  readonly valid: boolean;
  /** Number of entries the check read. */
  readonly checked: number;
  readonly brokenAt: number | null;
  readonly reason: AuditChainBreak | null;
  readonly trigger: AuditVerificationTrigger;
  readonly triggeredBy: string | null;
}

/** A live check of the chain that the server does not store (`GET /admin/audit/verify`). */
export interface AuditChainCheck {
  readonly valid: boolean;
  readonly checked: number;
  readonly brokenAt: number | null;
  readonly reason: string | null;
}

/** Cursor-paged audit response (keyset on `id`, newest first). */
export interface AuditPage {
  readonly items: readonly AuditEntry[];
  readonly nextCursor: number | null;
  readonly hasMore: boolean;
}

/** Distinct actor for the audit actor filter. */
export interface AuditActor {
  readonly sub: string;
  readonly name: string | null;
}

/**
 * A config snapshot (version sidebar). The list is append-only. Nobody can delete an
 * earlier version. `isCurrent` marks the active state.
 */
export interface ConfigRevision {
  readonly id: Uuid;
  readonly entityType: string;
  readonly entityId: string;
  readonly version: number;
  readonly at: string;
  readonly createdBy: string | null;
  readonly createdByName: string | null;
  readonly isCurrent: boolean;
}

/** Field diff of a config snapshot against its predecessor (wire form). */
export interface ConfigRevisionDiffWire {
  readonly id: Uuid;
  readonly entityType: string;
  readonly entityId: string;
  readonly version: number;
  readonly prevVersion: number | null;
  readonly diff: DataDiffWire;
}

/** Field diff of a config snapshot (FE view). `diff` is in array form for `@for`. */
export interface ConfigRevisionDiff {
  readonly id: Uuid;
  readonly entityType: string;
  readonly entityId: string;
  readonly version: number;
  readonly prevVersion: number | null;
  readonly diff: DataDiff | null;
}

/** Result of an audit-log revert. */
export interface AuditRevertResult {
  readonly revertedAuditId: number;
  readonly entityType: string;
  readonly entityId: string;
}

/** Platform notification config (P admin.notifications). */
export interface NotificationSettings {
  readonly taskReminderEnabled: boolean;
  /** Days without a status change before the platform sends a reminder (≥ 1). */
  readonly taskReminderAfterDays: number;
  /** Then again every N days. 0 = only once per state visit. */
  readonly taskReminderRepeatDays: number;
}

/**
 * Settings for applications without an account (P admin.deadlines):
 * `GET/PUT /admin/guest-settings`.
 */
export interface GuestSettings {
  /** Hours until the platform discards an unconfirmed guest application (1 to 720). */
  readonly confirmTtlHours: number;
  /** Lifetime of a new personal link in days (1 to 3650). `null` = no expiry. */
  readonly linkTtlDays: number | null;
  readonly updatedAt?: string | null;
  readonly updatedBy?: string | null;
}

/** Upper bound of {@link GuestSettings.confirmTtlHours} (`MAX_CONFIRM_TTL_HOURS`). */
export const MAX_CONFIRM_TTL_HOURS = 720;
/** Upper bound of {@link GuestSettings.linkTtlDays} (`MAX_LINK_TTL_DAYS`). */
export const MAX_LINK_TTL_DAYS = 3650;

/**
 * The open window of meetings (P admin.deadlines): `GET/PUT /admin/meeting-settings`.
 * Both values are minutes before the planned start of a meeting.
 */
export interface MeetingSettings {
  /** The earliest open (0 to 10080). */
  readonly openLeadMinutes: number;
  /** Before this point the open needs an extra confirmation (0 to `openLeadMinutes`). */
  readonly confirmLeadMinutes: number;
}

/**
 * Lifetimes of an SSO login (P admin.users): `GET/PUT /admin/login-settings`.
 *
 * A login stays valid for that many days after its last use (sliding). A change applies
 * to every session at its next renewal.
 */
export interface LoginSettings {
  /** Days a login in a browser tab stays valid after its last use (1 to 400). */
  readonly webSessionDays: number;
  /** Days a login in the installed app (PWA) stays valid after its last use (1 to 400). */
  readonly pwaSessionDays: number;
  readonly updatedAt?: string | null;
  readonly updatedBy?: string | null;
}

/** Upper bound of both {@link MeetingSettings} values (`MAX_LEAD_MINUTES`, one week). */
export const MAX_LEAD_MINUTES = 10080;

/**
 * Upper bound of both {@link LoginSettings} lifetimes. Browsers cap the lifetime of a
 * cookie at 400 days, so a longer session would end with its cookie anyway.
 */
export const MAX_SESSION_DAYS = 400;

/** DSGVO erasure request (queue, P privacy.manage). */
export type ErasureSubjectType = 'applicant' | 'principal';
export type ErasureStatus = 'open' | 'executed' | 'rejected';

export interface ErasureRequest {
  readonly id: Uuid;
  readonly createdAt: string;
  readonly subjectType: ErasureSubjectType;
  readonly applicationId?: Uuid | null;
  readonly principalId?: Uuid | null;
  readonly email?: string | null;
  readonly status: ErasureStatus;
  readonly requestedBy?: string | null;
  readonly handledBy?: string | null;
  readonly handledAt?: string | null;
  readonly reason?: string | null;
}

/** Platform-wide DSGVO config (global retention default, P privacy.manage). */
export interface PrivacySettings {
  readonly defaultRetentionMonths: number;
}

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
  readonly id: Uuid;
  readonly kind: BackupKind;
  readonly status: BackupStatus;
  readonly createdAt: string;
  readonly finishedAt?: string | null;
  /** OIDC `sub` of whoever started it. Null for the nightly job. */
  readonly createdBy?: string | null;
  readonly sizeBytes?: number | null;
  readonly objectCount?: number | null;
  readonly checksum?: string | null;
  readonly note?: string | null;
  readonly appVersion?: string | null;
  readonly schemaRevision?: string | null;
  /** A pinned archive is never pruned by retention and cannot be deleted. */
  readonly pinned: boolean;
  /** Short failure code. Never carries a path. */
  readonly error?: string | null;
}

/** The catalogue plus what this installation can actually do. */
export interface BackupList {
  readonly items: readonly Backup[];
  /** False without an age recipient: creating is off and the page says why. */
  readonly enabled: boolean;
  /** False without the private key: the platform cannot read its own archives. */
  readonly restoreEnabled: boolean;
  readonly retentionCount: number;
}

/** The literal a restore has to carry. It is a machine token, never translated. */
export const BACKUP_RESTORE_CONFIRMATION = 'RESTORE';

export type LogoSlot = 'wordmark' | 'imagemark' | 'favicon';

export interface BrandingAsset {
  /** Data URL or server-side asset URL of the image mark. */
  readonly url: string;
  readonly filename: string;
  readonly mime: string;
  /** Size in bytes (for the mime/size hint display). */
  readonly size: number;
}

export interface FooterLink {
  label: I18nMap;
  url: string;
}

export interface SiteFreetexts {
  /** Login hint, landing/welcome, support, email footer — each i18n. */
  loginHint: I18nMap;
  welcome: I18nMap;
  support: I18nMap;
  emailFooter: I18nMap;
  /** Info text below the application(-type) selection — Markdown, each i18n. */
  applyInfo?: I18nMap;
  /**
   * The text after the submission for a signed-in applicant ("intern") and for a guest
   * ("extern") — Markdown, each i18n. Empty ⇒ the built-in text of the language.
   */
  submittedInternal?: I18nMap;
  submittedExternal?: I18nMap;
  /** The accessibility statement of `/accessibility` — Markdown, each i18n. */
  readonly accessibilityStatement?: I18nMap;
}

export interface Branding {
  /** Full app name (browser tab, header, home page). Empty ⇒ the i18n default. */
  appName?: string;
  /** Short app name (PWA icon/home screen). Empty ⇒ the default. */
  appShortName?: string;
  logos: Partial<Record<LogoSlot, BrandingAsset>>;
  copyright: I18nMap;
  legalLinks: FooterLink[];
  freetexts: SiteFreetexts;
  /** Show the Gravatar images of the avatars. Missing (an older config) = on. */
  gravatarEnabled?: boolean;
  /** The accent colour of the app (`#rrggbb`). Missing or null = the built-in accent. */
  accentColor?: string | null;
  /** The handbook link of the help menu (page "Hilfe & Tickets"). */
  help?: { wikiUrl: string };
  /** The ticket settings (page "Hilfe & Tickets"). */
  tickets?: { publicEnabled: boolean; notifyNew: boolean; retentionMonths: number | null };
}

/**
 * The page "Funktionen" (`GET`/`PUT /admin/features`, permission `admin.features`): the
 * stored switch of each feature. A save writes a new active site-config version.
 */
export type FeatureSwitches = Readonly<Record<FeatureKey, boolean>>;

/**
 * The page "Hilfe & Tickets" (`GET`/`PUT /admin/help-tickets`, permission `admin.site`).
 * A save writes a new active site-config version.
 */
export interface HelpTicketsSettings {
  /** http(s) only. */
  readonly wikiUrl: string;
  /** Visitors without an account may send a ticket. */
  readonly publicEnabled: boolean;
  /** A new ticket mails the holders of `ticket.manage`. */
  readonly notifyNew: boolean;
  /** Months after the close until the reporter is anonymized (1 to 120); null = never. */
  readonly retentionMonths: number | null;
}

/** Versioned site config: active version + editable draft. */
/** `GET`/`PUT /admin/site-config`: the active branding and its version. */
export interface SiteConfig {
  readonly version: number;
  readonly branding: Branding;
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

/**
 * The export logo of every exported PDF except the protocol (spec 000891). Its bytes go
 * to the PDF renderer only, never to the browser, so SVG and PDF are allowed here, and
 * the page shows no preview of it.
 */
export interface ExportLogo {
  readonly fileName: string;
  readonly mime: string;
  readonly size: number;
}
export const EXPORT_LOGO_ACCEPT_MIME: readonly string[] = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/svg+xml',
  'application/pdf',
] as const;

/** Re-export so admin code imports only from `admin.models`. */
export type { FormFieldDef };

/**
 * Pattern for the key of a new role (global role and gremium role). It mirrors
 * `ROLE_KEY_PATTERN` in `backend/app/modules/admin/schemas.py`. The server refuses
 * a key that does not match with 422. A key never changes after the create.
 */
export const ROLE_KEY_PATTERN = /^[a-z][a-z0-9_]*$/;
