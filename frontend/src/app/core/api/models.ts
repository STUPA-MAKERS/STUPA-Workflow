/**
 * API DTOs — derived from the OpenAPI contracts. The backend OpenAPI is the
 * single source of truth; these types are the FE-side mirror for the typed API
 * client. On a contract change, coordinate rather than break unilaterally.
 *
 * Layout:
 *  - `*Wire` types mirror the backend JSON 1:1 (`_CamelModel`: camelCase aliases
 *    via `by_alias`). They are not consumed directly in components but translated
 *    into FE view models in the `ApiClient` layer via `mappers.ts`.
 *  - View models (`Application`, `ApplicationComment`, …) are the FE-friendly
 *    shapes (i18n label already resolved, boolean convenience fields). They are
 *    what components/templates see.
 *  - `*Body` types are request bodies in the camelCase wire form.
 */

export type Uuid = string;
export type IsoDateTime = string;
export type Lang = 'de' | 'en';

/** Configurable multilingual text (`*_i18n` JSONB). */
export type I18nMap = Record<string, string>;

/** Public (auth-free) active branding config — deliberately loosely typed: the FE
 *  reads only the free texts (e.g. `applyInfo`) and the app name from it. */
export interface PublicSiteConfig {
  version: number;
  branding?: {
    /** Configured app name (language-neutral); empty ⇒ i18n/default fallback. */
    appName?: string;
    /** Short name (PWA icon); empty ⇒ default fallback. */
    appShortName?: string;
    freetexts?: Partial<
      Record<'loginHint' | 'welcome' | 'support' | 'emailFooter' | 'applyInfo', I18nMap>
    >;
  } | null;
}

/** Uniform problem object (close to RFC 9457). */
export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  errors?: { field: string; msg: string }[];
  traceId?: string;
}

/**
 * Principal (OIDC) incl. roles/permissions/groups — GET /api/auth/me.
 * Field names mirror the backend `MeOut` 1:1. `MeOut` is a plain `BaseModel`
 * (not a `_CamelModel`) → `display_name` stays snake_case.
 */
/** Lean gremium reference (a principal's membership). */
export interface GremiumRef {
  id: Uuid;
  name: string;
  slug: string;
}

export interface Principal {
  sub: Uuid;
  email?: string | null;
  display_name?: string | null;
  roles: string[];
  permissions: string[];
  groups: string[];
  /** Gremien the principal is a member of — basis for "My gremien". */
  gremien?: GremiumRef[];
  /** Gremien the principal manages (gremium role with `session.manage`). */
  session_manage_gremien?: Uuid[];
  /** ≥1 cost centre is assigned to a member gremium. */
  has_scoped_budget_view?: boolean;
  /** Principal is in ≥1 substitute pool — meeting timeline visible. */
  in_substitute_pool?: boolean;
}

/** Response of POST /api/auth/logout — RP-initiated logout URL (OIDC) or null. */
export interface LogoutOut {
  logout_url: string | null;
}

/** Uniform list envelope (offset paging). */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApplicationListQuery {
  state?: string;
  gremium?: Uuid;
  type?: Uuid;
  topf?: Uuid;
  /** Cost centre (budget tree) incl. subtree. */
  budget?: Uuid;
  q?: string;
  amountMin?: number;
  amountMax?: number;
  createdFrom?: string;
  createdTo?: string;
  sort?: 'createdAt' | 'amount';
  order?: 'asc' | 'desc';
  /** Own applications only — forces the owner filter even with `application.read`. */
  mine?: boolean;
  limit?: number;
  offset?: number;
}

// =========================================================================== //
// Wire DTOs — exact mirror of the backend JSON (`_CamelModel`).                //
// =========================================================================== //

/** `StateOut` — `label` is an i18n map. */
export interface StateOutWire {
  id: Uuid;
  key: string;
  label: I18nMap;
  /** Display colour of the state badge (hex), optional. */
  color?: string | null;
  editAllowed: boolean;
  /** State kind: normal|vote. */
  kind?: string;
}

/** `ApplicantOut` — PII, filled only for authorized readers. */
export interface ApplicantOutWire {
  email?: string | null;
  name?: string | null;
  anonymized: boolean;
}

/** `ApplicationOut` — application detail. */
export interface ApplicationOutWire {
  id: Uuid;
  typeId: Uuid;
  state?: StateOutWire | null;
  gremiumId?: Uuid | null;
  budgetPotId?: Uuid | null;
  budgetId?: Uuid | null;
  fiscalYearId?: Uuid | null;
  amount?: string | null;
  currency?: string | null;
  data: Record<string, unknown>;
  version: number;
  lang?: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  applicant?: ApplicantOutWire | null;
  canEdit?: boolean;
  isOwner?: boolean;
}

/** `ApplicationListItem` — list entry (no `data`/`applicant`). */
export interface ApplicationListItemWire {
  id: Uuid;
  typeId: Uuid;
  title?: string | null;
  state?: StateOutWire | null;
  gremiumId?: Uuid | null;
  budgetPotId?: Uuid | null;
  amount?: string | null;
  currency?: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

/** `ApplicationCreated` — 201 response to `POST /applications` (id only). */
export interface ApplicationCreatedWire {
  applicationId: Uuid;
}

/** Attendance status of a member in a meeting. */
export type AttendanceStatus = 'present' | 'excused' | 'absent';

/** `AttendanceOut` — attendance of a gremium member (GET/PUT …/attendance). */
/** Current gremium member — protokollant candidate when creating a meeting. */
export interface MeetingMember {
  principalId: Uuid;
  displayName: string | null;
  email: string | null;
}

export interface Attendance {
  principalId: Uuid;
  displayName: string | null;
  email: string | null;
  /** `null` = not recorded yet. */
  status: AttendanceStatus | null;
  source: 'self' | 'lead' | null;
  /** Is this the requesting user (for self-marking)? */
  isSelf: boolean;
}

/** `AgendaItemOut` — an agenda item: linked application or free text. */
export interface AgendaItem {
  id: Uuid;
  /** `null` for a free-text agenda item (no application). */
  applicationId: Uuid | null;
  title: string | null;
  /** Markdown text of this agenda item (per-item editor). */
  body?: string | null;
  position: number;
  /** Non-public: redacted in the public protocol PDF. */
  nonPublic?: boolean;
  stateLabel?: I18nMap | null;
}

/** `AssignableApplicationOut` — application in a vote state, not yet on the agenda. */
export interface AssignableApplication {
  applicationId: Uuid;
  title: string | null;
  stateLabel?: I18nMap | null;
}

/** `AltchaChallengeOut` — server-signed PoW challenge (GET /altcha/challenge). */
export interface AltchaChallenge {
  algorithm: string;
  challenge: string;
  salt: string;
  signature: string;
  maxnumber: number;
}

/** `TimelineEventOut` — status transition in the timeline. */
export interface TimelineEventOutWire {
  fromStateId?: Uuid | null;
  toStateId: Uuid;
  toState?: StateOutWire | null;
  actor?: string | null;
  at: IsoDateTime;
  note?: string | null;
}

export type CommentVisibility = 'internal' | 'public';
export type CommentAuthorKind = 'principal' | 'applicant';

/** `CommentOut` — real backend field names: `author`/`authorKind`/`visibility`/`at`. */
export interface CommentOutWire {
  id: Uuid;
  author?: string | null;
  authorKind: CommentAuthorKind;
  body: string;
  visibility: CommentVisibility;
  at: IsoDateTime;
  /** Viewer wrote this comment (server-side determined — chat alignment). */
  isOwn?: boolean;
}

/** `ApplicationTypeListItem`. */
export interface ApplicationTypeListItemWire {
  id: Uuid;
  name: string;
  hasBudget: boolean;
  active: boolean;
  activeFormVersionId?: Uuid | null;
  /** Admin extra fields (filled only when authorized). */
  key?: string | null;
  gremiumId?: Uuid | null;
}

/** `TransitionOut` — `label` is an i18n map. */
export interface TransitionOutWire {
  id: Uuid;
  fromStateId: Uuid;
  toStateId: Uuid;
  label: I18nMap;
  /** Optional colour for the decision button. */
  color?: string | null;
}

/** A field change in the version diff (`FieldChange`). */
export interface FieldChangeWire {
  old: unknown;
  new: unknown;
}

/**
 * Structural diff of two `data` snapshots (`DataDiff`):
 * `added`/`removed` are field-value maps, `changed` maps key → `{old,new}`.
 * Nested fields are compared whole-value (no recursive cell diff) — robust
 * against heterogeneous tables/objects.
 */
export interface DataDiffWire {
  added: Record<string, unknown>;
  removed: Record<string, unknown>;
  changed: Record<string, FieldChangeWire>;
}

/** `VersionOut` — one submission version + diff. */
export interface VersionOutWire {
  version: number;
  data: Record<string, unknown>;
  diff?: DataDiffWire | null;
  changedBy?: string | null;
  at: IsoDateTime;
}

/**
 * `AttachmentOut` — attachment metadata. Plain `BaseModel` (not a `_CamelModel`)
 * → `is_comparison_offer` stays snake_case. `scanned` = ClamAV run finished (not
 * "clean"!): the scan result (`scan_result`) is deliberately not exposed; a
 * positive finding ⇒ the object is deleted. Clean-vs-finding only resolves at
 * download time (200 vs. 409).
 */
export interface AttachmentOutWire {
  id: Uuid;
  filename: string;
  mime: string;
  size: number;
  scanned: boolean;
  is_comparison_offer: boolean;
}

/** `SignedUrlOut` (files/schemas.py) — app-relative authz-gated /download route; expiresIn is an advisory FE cache hint, not a URL expiry. */
export interface SignedUrlOutWire {
  url: string;
  expiresIn: number;
}

// --- Request bodies (camelCase wire form) ---------------------------------- //

/** Body for `POST /applications` (`ApplicationCreate`, by_alias). */
export interface ApplicationCreateBody {
  typeId: Uuid;
  budgetPotId?: Uuid | null;
  data: Record<string, unknown>;
  // Optional: for logged-in users the backend derives identity from the account;
  // anonymous submission enforces it server-side.
  applicantEmail?: string | null;
  applicantName?: string | null;
  lang: Lang;
  altcha?: string | null;
}

/** Body for `POST /applications/{id}/comments` (`CommentCreate`). */
export interface CommentCreateBody {
  body: string;
  visibility: CommentVisibility;
}

/** Body for `POST /applications/{id}/transition` (`TransitionRequest`). */
export interface TransitionRequestBody {
  transitionId: Uuid;
  note?: string | null;
}

/** `POST /applications/{id}/force-status` — privileged direct status override.
 *  `note` (reason) is mandatory: the change bypasses the flow and is audited. */
export interface ForceStatusBody {
  stateId: Uuid;
  note: string;
}

/** `TransitionResult` — 200 response of a successful transition. */
export interface TransitionResult {
  newStateId: Uuid;
  statusEventId: Uuid;
  dispatchedActions: string[];
}

// =========================================================================== //
// View models — FE-friendly, i18n already resolved (output of mappers.ts).      //
// =========================================================================== //

/** Application status with resolved label (for the current `lang`). */
export interface ApplicationState {
  id: Uuid;
  key: string;
  label: string;
  /** Display colour of the state badge (hex), optional. */
  color?: string | null;
  editAllowed: boolean;
  /** State kind: normal|vote. */
  kind: string;
}

export interface Applicant {
  email: string | null;
  name: string | null;
  anonymized: boolean;
}

export interface Application {
  id: Uuid;
  typeId: Uuid;
  state: ApplicationState | null;
  gremiumId: Uuid | null;
  budgetPotId: Uuid | null;
  budgetId: Uuid | null;
  fiscalYearId: Uuid | null;
  amount: string | null;
  currency: string | null;
  data: Record<string, unknown>;
  version: number;
  lang: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  applicant: Applicant | null;
  /** May the requester edit/delete (manager or creator)? */
  canEdit: boolean;
  /** Is the requester the creator (applicant)? Gates the anonymization request
   *  (GDPR Art. 17) — only the data subject. */
  isOwner: boolean;
}

export interface ApplicationListItem {
  id: Uuid;
  typeId: Uuid;
  title: string | null;
  state: ApplicationState | null;
  gremiumId: Uuid | null;
  budgetPotId: Uuid | null;
  amount: string | null;
  currency: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

/** Result of `POST /applications` (FE view). */
export interface ApplicationCreated {
  applicationId: Uuid;
}

/** Timeline entry (FE view) — `label` resolved from `toState`. */
export interface TimelineEntry {
  toStateId: Uuid;
  toState: ApplicationState | null;
  label: string;
  actor: string | null;
  at: IsoDateTime;
  note: string | null;
}

/** Comment (FE view) — `isPublic` derived from `visibility`. */
export interface ApplicationComment {
  id: Uuid;
  author: string | null;
  authorKind: CommentAuthorKind;
  body: string;
  visibility: CommentVisibility;
  isPublic: boolean;
  /** Viewer wrote this comment — own messages right, all others left/gray. */
  isOwn: boolean;
  at: IsoDateTime;
}

/** Application type (FE view) for the wizard selection. */
export interface ApplicationType {
  id: Uuid;
  name: string;
  active: boolean;
  hasBudget: boolean;
  activeFormVersionId: Uuid | null;
  key: string | null;
  gremiumId: Uuid | null;
}

/** Available transition (FE view) — `label` resolved. */
export interface Transition {
  id: Uuid;
  fromStateId: Uuid;
  toStateId: Uuid;
  label: string;
  /** Optional colour for the decision button; null = default. */
  color: string | null;
}

/** A changed field cell (FE view) — `key` pulled out of the diff map. */
export interface FieldChange {
  key: string;
  old: unknown;
  new: unknown;
}

/**
 * Version diff (FE view) — the backend maps (`added`/`removed`/`changed`) are
 * resolved here into iterable, key-carrying lists so templates can render over
 * them directly with `@for`.
 */
export interface DataDiff {
  added: { key: string; value: unknown }[];
  removed: { key: string; value: unknown }[];
  changed: FieldChange[];
}

/** A submission version (FE view) for the history/diff view. */
export interface ApplicationVersion {
  version: number;
  data: Record<string, unknown>;
  diff: DataDiff | null;
  changedBy: string | null;
  at: IsoDateTime;
}

/**
 * Scan state of an attachment (FE view). Derivable from the contract:
 * - `scanning`    — `scanned=false`: ClamAV still running, no download (→ 409).
 * - `clean`       — `scanned=true`: scan finished; download generally possible.
 * - `quarantined` — set client-side when the download is rejected with 409
 *   (finding/quarantine) — the metadata alone does not reveal this.
 */
export type ScanState = 'scanning' | 'clean' | 'quarantined';

/** Attachment (FE view) — `isComparisonOffer` camelCase, `scanState` derived. */
export interface Attachment {
  id: Uuid;
  filename: string;
  mime: string;
  size: number;
  scanned: boolean;
  isComparisonOffer: boolean;
  scanState: ScanState;
}

/** Signed download URL (FE view). */
export interface SignedUrl {
  url: string;
  expiresIn: number;
}

/** FE input for a new application → mapped to `ApplicationCreateBody`. */
export interface NewApplication {
  typeId: Uuid;
  budgetPotId?: Uuid | null;
  data: Record<string, unknown>;
  // Null for logged-in users — the backend derives identity/altcha.
  applicantEmail?: string | null;
  applicantName?: string | null;
  lang: Lang;
  altcha?: string | null;
}

// --- Form definition — mirror of FormFieldDef ---------------------------------

export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'currency'
  | 'date'
  | 'select'
  | 'multiselect'
  // Dynamic pickers: options injected server-side (committees / budget tree).
  | 'gremium_select'
  | 'budget_select'
  // Typed inputs with built-in validation.
  | 'email'
  | 'iban'
  // Date range {from, to}.
  | 'daterange'
  | 'checkbox'
  | 'file'
  | 'table'
  | 'markdown'
  | 'computed'
  | 'positions'
  | 'section';

export interface FieldOption {
  value: string;
  label: I18nMap;
}

export interface FieldValidation {
  min?: number;
  max?: number;
  minLen?: number;
  maxLen?: number;
  pattern?: string;
  fileTypes?: string[];
  maxSizeMB?: number;
  maxRows?: number;
  /** `positions`: min comparison offers per position / min number of positions. */
  minOffers?: number;
  minPositions?: number;
}

/** A field definition of the effective form (camelCase like the OpenAPI by_alias). */
export interface FormFieldDef {
  key: string;
  type: FieldType;
  label: I18nMap;
  help?: I18nMap;
  required?: boolean;
  validation?: FieldValidation;
  options?: FieldOption[];
  visibleIf?: Record<string, unknown>;
  compute?: Record<string, unknown>;
  isPII?: boolean;
  isPromoted?: boolean;
  promoteTarget?: string;
}

export interface FormSection {
  key: string;
  label: I18nMap;
  fields: FormFieldDef[];
}

/** Effective form definition — GET /api/application-types/{id}/form. */
export interface EffectiveForm {
  applicationTypeId: Uuid;
  formVersionId: Uuid;
  budgetPotId?: Uuid | null;
  sections: FormSection[];
}

// --- Magic link ---------------------------------------------------------------

/**
 * Response of POST /api/auth/magic-link/verify (`MagicLinkVerifyOut`). Plain
 * `BaseModel` (not a `_CamelModel`) → field names stay snake_case
 * (`application_id`). The applicant session runs exclusively via an HttpOnly
 * cookie — no session token in the body/JS.
 */
export interface MagicLinkVerifyResult {
  application_id: Uuid;
  scope: 'edit' | 'view';
}

// --- Voting -------------------------------------------------------------------

export type MajorityRule = 'simple' | 'absolute' | 'two_thirds';
/** `cancelled` — application left the vote state manually (vote aborted). */
export type VoteStatus = 'draft' | 'open' | 'closed' | 'cancelled';
export type VoteResult = 'passed' | 'rejected' | 'tie';

/** Quorum threshold. */
export interface Quorum {
  type: 'count' | 'percent';
  value: number;
}

/**
 * Vote configuration (`VoteConfig`). Fields arrive camelCase via the backend
 * `_CamelModel`; defaults mirror the Pydantic defaults (`abstainCountsQuorum`/
 * `allowChange` true, `secret` false).
 */
export interface VoteConfig {
  options: string[];
  majorityRule: MajorityRule;
  quorum?: Quorum | null;
  abstainCountsQuorum?: boolean;
  secret?: boolean;
  allowChange?: boolean;
  tieBreak?: VoteResult;
}

/**
 * Aggregated interim/final result (`TallyOut`). For `secret` the server returns
 * only `counts` — never individual voters.
 */
export interface Tally {
  counts: Record<string, number>;
  eligible: number;
  quorumMet: boolean;
  leading: string | null;
  result?: VoteResult | null;
}

/**
 * Vote state + tally — GET /api/votes/{id} (`VoteOut`). Plain `_CamelModel`, so
 * usable 1:1 as a view model (no i18n label; options are raw keys the FE
 * translates via `vote.option.*`).
 */
export interface Vote {
  id: Uuid;
  applicationId: Uuid;
  eligibleGroup: string;
  config: VoteConfig;
  status: VoteStatus;
  opensAt: IsoDateTime | null;
  closesAt: IsoDateTime | null;
  result: VoteResult | null;
  secret: boolean;
  tally: Tally;
}

/** Response to an accepted ballot — POST /api/votes/{id}/ballot. */
export interface BallotResult {
  status: 'cast' | 'changed';
}

// =========================================================================== //
// Meetings + protocol. Wire form camelCase (`_CamelModel`).                     //
// =========================================================================== //

/** Meeting status; BE enum: `planned|live|closed`. */
export type MeetingStatus = 'planned' | 'live' | 'closed';
/** Status of a vote within a meeting. */
/** `cancelled` — application left the vote state manually (vote aborted). */
export type MeetingVoteStatus = 'pending' | 'open' | 'closed' | 'cancelled';

/** `MeetingVoteOut` — vote summary in the meeting state (GET /meetings/{id}). */
export interface MeetingVoteOutWire {
  id: Uuid;
  /** `null` = generic motion (free-text agenda item), no application. */
  applicationId?: Uuid | null;
  /** Which agenda item the vote is bound to (grouping in the FE). */
  agendaItemId?: Uuid | null;
  /** Application title (supplied by the backend; else resolved from the application). */
  title?: string | null;
  /** Motion of the (live) vote — for the protocol. */
  question?: string | null;
  /** Options (for casting). */
  options?: string[] | null;
  status: MeetingVoteStatus;
  /** Final result (e.g. `accepted`/`rejected`), only after `closed`. */
  result?: string | null;
  counts?: Record<string, number> | null;
  leading?: string | null;
  closesAt?: IsoDateTime | null;
  voted?: number | null;
  present?: number | null;
  revealed?: boolean | null;
  /** Reason for rejection: `quorum` = quorum missed, `majority` = majority missed. */
  failedReason?: 'quorum' | 'majority' | null;
}

/** `MeetingOut` — meeting state + votes (GET /meetings/{id}). */
export interface MeetingOutWire {
  id: Uuid;
  title: string;
  date?: string | null;
  startTime?: string | null;
  endTime?: string | null;
  status: MeetingStatus;
  activeApplicationId?: Uuid | null;
  gremiumId?: Uuid | null;
  gremiumName?: string | null;
  votes: MeetingVoteOutWire[];
  /** Linked protocol (if already created). */
  protocolId?: Uuid | null;
  createdAt: IsoDateTime;
  protokollantId?: Uuid | null;
  protokollantName?: string | null;
  /** Is the requesting user the assigned protokollant? (resolved server-side). */
  isProtokollant?: boolean;
  /** Master flag: may the user run the meeting (protocol/agenda/status)? */
  canControl?: boolean;
  /** Manage the meeting (create/plan/assign protokollant). */
  canManage?: boolean;
  /** Write protocol/agenda (assigned protokollant or manager). */
  canWrite?: boolean;
  /** Open/close motions. */
  canManageVotes?: boolean;
  /** Eligible to vote in this meeting (role with vote.cast). */
  canVote?: boolean;
}

/** `ProtocolOut` — meeting protocol (POST /meetings/{id}/protocol, PATCH /protocols/{id}). */
export interface ProtocolOutWire {
  id: Uuid;
  meetingId: Uuid;
  markdown: string;
  /** `rendering` = finalize triggered, the worker renders the PDF in the background. */
  status: 'draft' | 'rendering' | 'final';
  /** Result link after `finalize` (PDF in MinIO). */
  pdfUrl?: string | null;
  /** Redacted public variant — set only when an agenda item is non-public. */
  publicPdfUrl?: string | null;
  sentAt?: IsoDateTime | null;
}

// --- Request bodies (camelCase wire form) ---------------------------------- //

/** Body for `POST /meetings` (`MeetingCreate`). */
export interface MeetingCreateBody {
  title: string;
  gremiumId?: Uuid | null;
  /** Planned meeting date (`YYYY-MM-DD`), optional. */
  date?: string | null;
  /** Planned time (`HH:mm`), optional. */
  startTime?: string | null;
  /** Planned end time (`HH:mm`), optional — must be after `startTime`. */
  endTime?: string | null;
  /** Assigned protokollant (member of the gremium), optional. */
  protokollantId?: Uuid | null;
}

/** Body for `PATCH /meetings/{id}` — status, active application, date and/or protokollant. */
export interface MeetingPatchBody {
  status?: MeetingStatus;
  activeApplicationId?: Uuid | null;
  /** Planned meeting date (`YYYY-MM-DD`); for pre-scheduling planned meetings. */
  date?: string | null;
  /** Planned time (`HH:mm`). */
  startTime?: string | null;
  /** Planned end time (`HH:mm`). */
  endTime?: string | null;
  /** (Re)assign the protokollant. */
  protokollantId?: Uuid | null;
}

/** Body for `PATCH /protocols/{id}` — update markdown. */
export interface ProtocolPatchBody {
  markdown: string;
}

/** Body for `POST /protocols/{id}/votes` — embed votes. */
export interface ProtocolVotesBody {
  voteIds: Uuid[];
}

/** `CalendarFeedOut` — own iCal subscription URL (`url` null until a token is created). */
export interface CalendarFeed {
  url: string | null;
}

// --- View models ----------------------------------------------------------- //

/** Vote summary (FE view) — `null` defaults normalized. */
export interface MeetingVote {
  id: Uuid;
  /** `null` = generic motion (free-text agenda item). */
  applicationId: Uuid | null;
  /** Agenda item the vote is bound to. */
  agendaItemId: Uuid | null;
  title: string | null;
  question: string | null;
  options: string[];
  status: MeetingVoteStatus;
  result: string | null;
  counts: Record<string, number> | null;
  leading: string | null;
  closesAt: IsoDateTime | null;
  /** Participation progress: voted vs. present members. `revealed` = whether
   *  `counts`/`leading` are visible (otherwise progress only). */
  voted: number;
  present: number;
  revealed: boolean;
  /** Reason for rejection: `quorum` = quorum missed, `majority` = majority missed. */
  failedReason: 'quorum' | 'majority' | null;
}

/** Meeting (FE view). */
export interface Meeting {
  id: Uuid;
  title: string;
  /** Planned meeting date (`YYYY-MM-DD`) or `null`. */
  date: string | null;
  /** Planned time (`HH:mm`) or `null`. */
  startTime: string | null;
  /** Planned end time (`HH:mm`) or `null`. */
  endTime: string | null;
  status: MeetingStatus;
  activeApplicationId: Uuid | null;
  gremiumId: Uuid | null;
  /** Name of the associated gremium (for the timeline display). */
  gremiumName: string | null;
  votes: MeetingVote[];
  protocolId: Uuid | null;
  createdAt: IsoDateTime;
  protokollantId: Uuid | null;
  protokollantName: string | null;
  /** Is the logged-in user the assigned protokollant of this meeting? */
  isProtokollant: boolean;
  /** Master flag: may the user run the meeting (protocol/agenda/status)? */
  canControl: boolean;
  /** Manage the meeting (create/plan/assign protokollant). */
  canManage: boolean;
  /** Write protocol/agenda (assigned protokollant or manager). */
  canWrite: boolean;
  /** Open/close motions. */
  canManageVotes: boolean;
  /** Eligible to vote in this meeting. */
  canVote: boolean;
}

/** Direction of the meeting timeline relative to *now*. */
export type TimelineDirection = 'past' | 'upcoming';

/** `MeetingPage` — cursor page of the timeline (wire). */
export interface MeetingPageWire {
  items: MeetingOutWire[];
  nextCursor?: string | null;
}

/** Meeting timeline page (FE view); `nextCursor === null` ⇒ end reached. */
export interface MeetingPage {
  items: Meeting[];
  nextCursor: string | null;
}

/** Protocol (FE view) — `isFinal`/`isLocked` derived from `status`. */
export interface Protocol {
  id: Uuid;
  meetingId: Uuid;
  markdown: string;
  status: 'draft' | 'rendering' | 'final';
  isFinal: boolean;
  /** Not editable: final or the worker is currently rendering (`rendering`). */
  isLocked: boolean;
  pdfUrl: string | null;
  /** Redacted public variant (non-public agenda items), else null. */
  publicPdfUrl: string | null;
  sentAt: IsoDateTime | null;
}

// =========================================================================== //
// Notification preferences — self-service via the account popout.               //
// =========================================================================== //

/** Toggle for a notification kind (`GET/PUT /notifications/preferences`). */
export interface NotificationPreference {
  kind: string;
  enabled: boolean;
}

// =========================================================================== //
// OAuth grants + MCP setup — self-service via the account popout.                //
// =========================================================================== //

/** An active OAuth grant (agent/MCP token) of the logged-in user. */
export interface OAuthGrant {
  id: string;
  clientId: string;
  scope: string;
  createdAt: IsoDateTime | null;
  accessExpiresAt: IsoDateTime;
  refreshExpiresAt: IsoDateTime | null;
}

/** Ready-made MCP setup snippet + metadata (GET /mcp/config). */
export interface McpSetup {
  mcpServers: Record<string, unknown>;
  baseUrl: string;
  clientId: string;
  scopesSupported: string[];
  install: string;
  note: string;
}

/** A scope row requested in the consent (held = user has the right). */
export interface ConsentScope {
  key: string;
  held: boolean;
}

/** Pending authorize request for the consent screen. */
export interface ConsentRequest {
  clientId: string;
  canUseMcp: boolean;
  requestedScopes: ConsentScope[];
  lifetimes: string[];
  defaultLifetime: string;
}
