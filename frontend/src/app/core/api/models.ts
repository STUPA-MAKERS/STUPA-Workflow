/**
 * API DTOs derived from the OpenAPI contracts. The backend OpenAPI is the single
 * source of truth. These types mirror it on the frontend side for the typed API
 * client. If a contract changes, coordinate the change. Do not break one side.
 *
 * Layout:
 *  - `*Wire` types mirror the backend JSON 1:1. `_CamelModel` gives camelCase
 *    aliases through `by_alias`. Components never read them. The `ApiClient` layer
 *    translates them into frontend view models through `mappers.ts`.
 *  - View models (`Application`, `ApplicationComment`, …) are the frontend-friendly
 *    shapes. They carry the resolved i18n label and boolean convenience fields.
 *    Components and templates see these.
 *  - `*Body` types are request bodies in the camelCase wire form.
 */

export type Uuid = string;
export type IsoDateTime = string;
export type Lang = 'de' | 'en';

/** Configurable multilingual text (`*_i18n` JSONB). */
export type I18nMap = Record<string, string>;

/** Public branding config of the active site version. It needs no authentication.
 *  The type stays loose on purpose. The frontend reads only the free texts, for
 *  example `applyInfo`, and the app name. */
export interface PublicSiteConfig {
  version: number;
  branding?: {
    /** Configured app name (language neutral). Empty falls back to i18n or the default. */
    appName?: string;
    /** Short name for the PWA icon. Empty falls back to the default. */
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
 * Principal (OIDC) with roles, permissions and groups. GET /api/auth/me.
 *
 * The field names mirror the backend `MeOut` 1:1. `MeOut` is a plain `BaseModel`
 * and not a `_CamelModel`, so `display_name` keeps its snake_case name.
 */
/** Small gremium reference. It names one membership of a principal. */
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
  /** Gremien the principal belongs to. This drives the "My gremien" view. */
  gremien?: GremiumRef[];
  /** Gremien the principal manages through a gremium role with `session.manage`. */
  session_manage_gremien?: Uuid[];
  /** At least one cost center belongs to a gremium of this principal. */
  has_scoped_budget_view?: boolean;
  /** The principal is in at least one substitute pool. The meeting timeline shows. */
  in_substitute_pool?: boolean;
}

/** Response of POST /api/auth/logout. An RP-initiated OIDC logout URL, or null. */
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
  /** Cost center in the budget tree. The filter includes the subtree. */
  budget?: Uuid;
  q?: string;
  amountMin?: number;
  amountMax?: number;
  createdFrom?: string;
  createdTo?: string;
  sort?: 'createdAt' | 'amount';
  order?: 'asc' | 'desc';
  /** Own applications only. It forces the owner filter even with `application.read`. */
  mine?: boolean;
  limit?: number;
  offset?: number;
}

/** `StateOut`. The `label` is an i18n map. */
export interface StateOutWire {
  id: Uuid;
  key: string;
  label: I18nMap;
  /** Optional display color of the state badge, as hex. */
  color?: string | null;
  editAllowed: boolean;
  /** State kind: normal|vote. */
  kind?: string;
}

/** `ApplicantOut`. It holds PII. The backend fills it only for an authorized reader. */
export interface ApplicantOutWire {
  email?: string | null;
  name?: string | null;
  anonymized: boolean;
}

/** `ApplicationOut`. The application detail. */
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

/** `ApplicationListItem`. A list entry without `data` and without `applicant`. */
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

/** `ApplicationCreated`. The 201 response of `POST /applications`. It holds only the id. */
export interface ApplicationCreatedWire {
  applicationId: Uuid;
}

/** Attendance status of a member in a meeting. */
export type AttendanceStatus = 'present' | 'excused' | 'absent';

/** `AttendanceOut`. Attendance of a gremium member. GET/PUT …/attendance. */
/** A current gremium member. This is a protokollant candidate for a new meeting. */
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
  /** True if this row is the requesting user. It enables self-marking. */
  isSelf: boolean;
}

/** `AgendaItemOut`. An agenda item holds a linked application or free text. */
export interface AgendaItem {
  id: Uuid;
  /** `null` for a free-text agenda item (no application). */
  applicationId: Uuid | null;
  title: string | null;
  /** Markdown text of this agenda item. Each item has its own editor. */
  body?: string | null;
  position: number;
  /** Non-public. The public protocol PDF redacts this agenda item. */
  nonPublic?: boolean;
  stateLabel?: I18nMap | null;
}

/** `AssignableApplicationOut`. An application in a vote state that is not on the agenda. */
export interface AssignableApplication {
  applicationId: Uuid;
  title: string | null;
  stateLabel?: I18nMap | null;
}

/** `AltchaChallengeOut`. A server-signed proof-of-work challenge. GET /altcha/challenge. */
export interface AltchaChallenge {
  algorithm: string;
  challenge: string;
  salt: string;
  signature: string;
  maxnumber: number;
}

/** `TimelineEventOut`. A status transition in the timeline. */
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

/** `CommentOut`. The backend field names are `author`, `authorKind`, `visibility`, `at`. */
export interface CommentOutWire {
  id: Uuid;
  author?: string | null;
  authorKind: CommentAuthorKind;
  body: string;
  visibility: CommentVisibility;
  at: IsoDateTime;
  /** True if the viewer wrote this comment. The server decides. It aligns the chat. */
  isOwn?: boolean;
}

/** `ApplicationTypeListItem`. */
export interface ApplicationTypeListItemWire {
  id: Uuid;
  name: string;
  hasBudget: boolean;
  active: boolean;
  activeFormVersionId?: Uuid | null;
  /** Extra admin fields. The backend fills them only for an authorized reader. */
  key?: string | null;
  gremiumId?: Uuid | null;
}

/** `TransitionOut`. The `label` is an i18n map. */
export interface TransitionOutWire {
  id: Uuid;
  fromStateId: Uuid;
  toStateId: Uuid;
  label: I18nMap;
  /** Optional color for the decision button. */
  color?: string | null;
}

/** A field change in the version diff (`FieldChange`). */
export interface FieldChangeWire {
  old: unknown;
  new: unknown;
}

/**
 * Structural diff of two `data` snapshots (`DataDiff`). `added` and `removed` are
 * field-value maps. `changed` maps a key to `{old,new}`.
 *
 * The backend compares a nested field as one whole value. It runs no recursive
 * cell diff. That also works for heterogeneous tables and objects.
 */
export interface DataDiffWire {
  added: Record<string, unknown>;
  removed: Record<string, unknown>;
  changed: Record<string, FieldChangeWire>;
}

/** `VersionOut`. One submission version and its diff. */
export interface VersionOutWire {
  version: number;
  data: Record<string, unknown>;
  diff?: DataDiffWire | null;
  changedBy?: string | null;
  at: IsoDateTime;
}

/**
 * `AttachmentOut`. Attachment metadata. It is a plain `BaseModel` and not a
 * `_CamelModel`, so `is_comparison_offer` keeps its snake_case name.
 *
 * `scanned` means that the ClamAV run finished. It does not mean "clean". The API
 * hides the scan result (`scan_result`) on purpose. If the scan finds something,
 * the backend deletes the object. Clean and infected only separate at download
 * time: 200 against 409.
 */
export interface AttachmentOutWire {
  id: Uuid;
  filename: string;
  mime: string;
  size: number;
  scanned: boolean;
  is_comparison_offer: boolean;
}

/**
 * `SignedUrlOut` (files/schemas.py). An app-relative /download route behind an
 * authorization check. `expiresIn` is an advisory cache hint for the frontend. It
 * is not a URL expiry.
 */
export interface SignedUrlOutWire {
  url: string;
  expiresIn: number;
}

/** Body for `POST /applications` (`ApplicationCreate`, by_alias). */
export interface ApplicationCreateBody {
  typeId: Uuid;
  budgetPotId?: Uuid | null;
  data: Record<string, unknown>;
  // Optional. For a logged-in user the backend takes the identity from the account.
  // For an anonymous submission the server requires these fields.
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

/** `POST /applications/{id}/force-status`. A privileged direct status override.
 *  `note` holds the reason and is mandatory. The change skips the flow. The audit
 *  log records it. */
export interface ForceStatusBody {
  stateId: Uuid;
  note: string;
}

/** `TransitionResult`. The 200 response of a transition that succeeded. */
export interface TransitionResult {
  newStateId: Uuid;
  statusEventId: Uuid;
  dispatchedActions: string[];
}

// View models. Frontend friendly, i18n already resolved. Built by `mappers.ts`.

/** Application status with the label resolved for the current `lang`. */
export interface ApplicationState {
  id: Uuid;
  key: string;
  label: string;
  /** Optional display color of the state badge, as hex. */
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
  /** True if the requester may edit or delete. A manager or the creator may. */
  canEdit: boolean;
  /** True if the requester is the creator, that is the applicant. It gates the
   *  anonymization request under GDPR Art. 17. Only the data subject may ask. */
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

/** Result of `POST /applications`, frontend view. */
export interface ApplicationCreated {
  applicationId: Uuid;
}

/** Timeline entry, frontend view. The `label` comes from `toState`. */
export interface TimelineEntry {
  toStateId: Uuid;
  toState: ApplicationState | null;
  label: string;
  actor: string | null;
  at: IsoDateTime;
  note: string | null;
}

/** Comment, frontend view. `isPublic` comes from `visibility`. */
export interface ApplicationComment {
  id: Uuid;
  author: string | null;
  authorKind: CommentAuthorKind;
  body: string;
  visibility: CommentVisibility;
  isPublic: boolean;
  /** True if the viewer wrote this comment. Own messages go right, others left and gray. */
  isOwn: boolean;
  at: IsoDateTime;
}

/** Application type, frontend view, for the wizard selection. */
export interface ApplicationType {
  id: Uuid;
  name: string;
  active: boolean;
  hasBudget: boolean;
  activeFormVersionId: Uuid | null;
  key: string | null;
  gremiumId: Uuid | null;
}

/** Available transition, frontend view, with the `label` resolved. */
export interface Transition {
  id: Uuid;
  fromStateId: Uuid;
  toStateId: Uuid;
  label: string;
  /** Optional color for the decision button. `null` selects the default. */
  color: string | null;
}

/** A changed field cell, frontend view. The `key` comes out of the diff map. */
export interface FieldChange {
  key: string;
  old: unknown;
  new: unknown;
}

/**
 * Version diff, frontend view. The backend sends the maps `added`, `removed` and
 * `changed`. This shape turns them into lists that carry the key. A template can
 * then render them directly with `@for`.
 */
export interface DataDiff {
  added: { key: string; value: unknown }[];
  removed: { key: string; value: unknown }[];
  changed: FieldChange[];
}

/** A submission version, frontend view, for the history and diff view. */
export interface ApplicationVersion {
  version: number;
  data: Record<string, unknown>;
  diff: DataDiff | null;
  changedBy: string | null;
  at: IsoDateTime;
}

/**
 * Scan state of an attachment, frontend view. The contract gives it:
 * - `scanning`: `scanned=false`. ClamAV still runs. A download returns 409.
 * - `clean`: `scanned=true`. The scan finished. A download normally works.
 * - `quarantined`: the client sets this when a download fails with 409, that is
 *   on a finding or a quarantine. The metadata alone does not show this state.
 */
export type ScanState = 'scanning' | 'clean' | 'quarantined';

/** Attachment, frontend view. `isComparisonOffer` is camelCase. `scanState` is derived. */
export interface Attachment {
  id: Uuid;
  filename: string;
  mime: string;
  size: number;
  scanned: boolean;
  isComparisonOffer: boolean;
  scanState: ScanState;
}

/** Signed download URL, frontend view. */
export interface SignedUrl {
  url: string;
  expiresIn: number;
}

/**
 * Status of an async render job (`JobOut.status`).
 *
 * `pending` means the job waits for the worker. `running` means the worker
 * renders. `done` and `failed` are the two end states. Nothing else follows.
 */
export type RenderJobStatus = 'pending' | 'running' | 'done' | 'failed';

/**
 * Async render job (`POST /applications/{id}/pdf`, `GET /jobs/{id}`).
 *
 * `resultUrl` holds a signed, short-lived MinIO link. It is set only on `done`,
 * and only when the deployment has an object store. `error` holds a short code,
 * for example `render_error`, and only on `failed`.
 */
export interface RenderJob {
  id: Uuid;
  kind: string;
  status: RenderJobStatus;
  applicationId: Uuid | null;
  resultUrl: string | null;
  error: string | null;
}

/** Frontend input for a new application. It maps to `ApplicationCreateBody`. */
export interface NewApplication {
  typeId: Uuid;
  budgetPotId?: Uuid | null;
  data: Record<string, unknown>;
  // Null for a logged-in user. The backend takes the identity and the altcha itself.
  applicantEmail?: string | null;
  applicantName?: string | null;
  lang: Lang;
  altcha?: string | null;
}

// Form definition. A mirror of the backend `FormFieldDef`.

export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'currency'
  | 'date'
  | 'select'
  | 'multiselect'
  // Dynamic pickers. The server injects the options: Gremien or the budget tree.
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
  /** `positions`. The minimum comparison offers per position and the minimum
   *  number of positions. */
  minOffers?: number;
  minPositions?: number;
  /** `positions`. Allow the opt-out of comparison offers for one position. The
   *  user ticks a checkbox and must give a reason. Then one offer is enough. If
   *  unset, the opt-out is allowed. */
  allowNoOffers?: boolean;
}

/** A field definition of the effective form. It is camelCase like the OpenAPI by_alias. */
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

/** Effective form definition. GET /api/application-types/{id}/form. */
export interface EffectiveForm {
  applicationTypeId: Uuid;
  formVersionId: Uuid;
  budgetPotId?: Uuid | null;
  sections: FormSection[];
}

/**
 * Response of POST /api/auth/magic-link/verify (`MagicLinkVerifyOut`). It is a
 * plain `BaseModel` and not a `_CamelModel`, so the field names stay snake_case,
 * for example `application_id`. The applicant session runs only through an
 * HttpOnly cookie. The body carries no session token. JavaScript never sees one.
 */
export interface MagicLinkVerifyResult {
  application_id: Uuid;
  scope: 'edit' | 'view';
}

export type MajorityRule = 'simple' | 'absolute' | 'two_thirds';
/** `cancelled`. The application left the vote state by hand. The vote stopped. */
export type VoteStatus = 'draft' | 'open' | 'closed' | 'cancelled';
export type VoteResult = 'passed' | 'rejected' | 'tie';

/** Quorum threshold. */
export interface Quorum {
  type: 'count' | 'percent';
  value: number;
}

/**
 * Vote configuration (`VoteConfig`). The backend `_CamelModel` sends the fields in
 * camelCase. The defaults mirror the Pydantic defaults: `abstainCountsQuorum` and
 * `allowChange` are true, `secret` is false.
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
 * Aggregated interim or final result (`TallyOut`). For a `secret` vote the server
 * returns only `counts`. It never returns an individual voter.
 */
export interface Tally {
  counts: Record<string, number>;
  eligible: number;
  quorumMet: boolean;
  leading: string | null;
  result?: VoteResult | null;
}

/**
 * Vote state and tally. GET /api/votes/{id} (`VoteOut`). It is a plain
 * `_CamelModel`, so the frontend uses it 1:1 as a view model. It carries no i18n
 * label. The options are raw keys. The frontend translates them through
 * `vote.option.*`.
 */
export interface Vote {
  id: Uuid;
  applicationId: Uuid;
  /** The meeting that holds the vote. `null` marks a standalone (async) vote.
   *  A meeting-bound vote is deleted through its meeting, never through
   *  `DELETE /votes/{id}` (that route answers 409). */
  meetingId?: Uuid | null;
  eligibleGroup: string;
  config: VoteConfig;
  status: VoteStatus;
  opensAt: IsoDateTime | null;
  closesAt: IsoDateTime | null;
  result: VoteResult | null;
  secret: boolean;
  tally: Tally;
}

/** Response to an accepted ballot. POST /api/votes/{id}/ballot. */
export interface BallotResult {
  status: 'cast' | 'changed';
}

// Meetings and protocol. The wire form is camelCase (`_CamelModel`).

/** Meeting status. The backend enum is `planned|live|closed`. */
export type MeetingStatus = 'planned' | 'live' | 'closed';
/** `cancelled`. The application left the vote state by hand. The vote stopped. */
export type MeetingVoteStatus = 'pending' | 'open' | 'closed' | 'cancelled';

/** `MeetingVoteOut`. A vote summary in the meeting state. GET /meetings/{id}. */
export interface MeetingVoteOutWire {
  id: Uuid;
  /** `null` marks a generic motion on a free-text agenda item, with no application. */
  applicationId?: Uuid | null;
  /** The agenda item the vote belongs to. The frontend groups by it. */
  agendaItemId?: Uuid | null;
  /** Application title. The backend supplies it. Otherwise read it from the application. */
  title?: string | null;
  /** Motion of the live vote. The protocol needs it. */
  question?: string | null;
  /** Options a voter can pick. */
  options?: string[] | null;
  status: MeetingVoteStatus;
  /** Final result, for example `accepted` or `rejected`. Set only after `closed`. */
  result?: string | null;
  counts?: Record<string, number> | null;
  leading?: string | null;
  closesAt?: IsoDateTime | null;
  voted?: number | null;
  present?: number | null;
  revealed?: boolean | null;
  /** Reason for the rejection. `quorum` means the vote missed the quorum.
   *  `majority` means the vote missed the majority. */
  failedReason?: 'quorum' | 'majority' | null;
}

/** `MeetingOut`. Meeting state and votes. GET /meetings/{id}. */
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
  /** The linked protocol, if it already exists. */
  protocolId?: Uuid | null;
  createdAt: IsoDateTime;
  protokollantId?: Uuid | null;
  protokollantName?: string | null;
  /** True if the requesting user is the assigned protokollant. The server resolves it. */
  isProtokollant?: boolean;
  /** Master flag. True if the user may run the meeting: protocol, agenda, status. */
  canControl?: boolean;
  /** Manage the meeting: create it, plan it and assign the protokollant. */
  canManage?: boolean;
  /** Write the protocol and the agenda. The assigned protokollant or a manager may. */
  canWrite?: boolean;
  /** Open and close motions. */
  canManageVotes?: boolean;
  /** Eligible to vote in this meeting. The user needs a role with `vote.cast`. */
  canVote?: boolean;
}

/** `ProtocolOut`. Meeting protocol. POST /meetings/{id}/protocol, PATCH /protocols/{id}. */
export interface ProtocolOutWire {
  id: Uuid;
  meetingId: Uuid;
  markdown: string;
  /** `rendering` means finalize ran. The worker renders the PDF in the background. */
  status: 'draft' | 'rendering' | 'final';
  /** Result link after `finalize`. The PDF sits in MinIO. */
  pdfUrl?: string | null;
  /** Redacted public variant. It exists only if an agenda item is non-public. */
  publicPdfUrl?: string | null;
  sentAt?: IsoDateTime | null;
}

/** Body for `POST /meetings` (`MeetingCreate`). */
export interface MeetingCreateBody {
  title: string;
  gremiumId?: Uuid | null;
  /** Planned meeting date (`YYYY-MM-DD`), optional. */
  date?: string | null;
  /** Planned time (`HH:mm`), optional. */
  startTime?: string | null;
  /** Planned end time (`HH:mm`), optional. It must be after `startTime`. */
  endTime?: string | null;
  /** Assigned protokollant, optional. The person must be a member of the gremium. */
  protokollantId?: Uuid | null;
}

/** Body for `PATCH /meetings/{id}`. Status, active application, date or protokollant. */
export interface MeetingPatchBody {
  status?: MeetingStatus;
  activeApplicationId?: Uuid | null;
  /** Planned meeting date (`YYYY-MM-DD`). Use it to schedule a planned meeting. */
  date?: string | null;
  /** Planned time (`HH:mm`). */
  startTime?: string | null;
  /** Planned end time (`HH:mm`). */
  endTime?: string | null;
  /** (Re)assign the protokollant. */
  protokollantId?: Uuid | null;
}

/** Body for `PATCH /protocols/{id}`. It updates the markdown. */
export interface ProtocolPatchBody {
  markdown: string;
}

/** Body for `POST /protocols/{id}/votes`. It embeds votes. */
export interface ProtocolVotesBody {
  voteIds: Uuid[];
}

/** `CalendarFeedOut`. The own iCal subscription URL. `url` is null until a token exists. */
export interface CalendarFeed {
  url: string | null;
}

// View models for meetings and protocol.

/** Vote summary, frontend view. It normalizes the `null` defaults. */
export interface MeetingVote {
  id: Uuid;
  /** `null` marks a generic motion on a free-text agenda item. */
  applicationId: Uuid | null;
  /** The agenda item the vote belongs to. */
  agendaItemId: Uuid | null;
  title: string | null;
  question: string | null;
  options: string[];
  status: MeetingVoteStatus;
  result: string | null;
  counts: Record<string, number> | null;
  leading: string | null;
  closesAt: IsoDateTime | null;
  /** Participation progress: members who voted against members present.
   *  `revealed` tells whether `counts` and `leading` are visible. If not, the
   *  frontend shows the progress only. */
  voted: number;
  present: number;
  revealed: boolean;
  /** Reason for the rejection. `quorum` means the vote missed the quorum.
   *  `majority` means the vote missed the majority. */
  failedReason: 'quorum' | 'majority' | null;
}

/** Meeting, frontend view. */
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
  /** Name of the gremium. The timeline shows it. */
  gremiumName: string | null;
  votes: MeetingVote[];
  protocolId: Uuid | null;
  createdAt: IsoDateTime;
  protokollantId: Uuid | null;
  protokollantName: string | null;
  /** True if the logged-in user is the assigned protokollant of this meeting. */
  isProtokollant: boolean;
  /** Master flag. True if the user may run the meeting: protocol, agenda, status. */
  canControl: boolean;
  /** Manage the meeting: create it, plan it and assign the protokollant. */
  canManage: boolean;
  /** Write the protocol and the agenda. The assigned protokollant or a manager may. */
  canWrite: boolean;
  /** Open and close motions. */
  canManageVotes: boolean;
  /** Eligible to vote in this meeting. */
  canVote: boolean;
}

/** Direction of the meeting timeline relative to *now*. */
export type TimelineDirection = 'past' | 'upcoming';

/** `MeetingPage`. A cursor page of the timeline, wire form. */
export interface MeetingPageWire {
  items: MeetingOutWire[];
  nextCursor?: string | null;
}

/** Meeting timeline page, frontend view. `nextCursor === null` marks the end. */
export interface MeetingPage {
  items: Meeting[];
  nextCursor: string | null;
}

/** Protocol, frontend view. `isFinal` and `isLocked` come from `status`. */
export interface Protocol {
  id: Uuid;
  meetingId: Uuid;
  markdown: string;
  status: 'draft' | 'rendering' | 'final';
  isFinal: boolean;
  /** Not editable. The protocol is final, or the worker renders it (`rendering`). */
  isLocked: boolean;
  pdfUrl: string | null;
  /** Redacted public variant for non-public agenda items. Otherwise null. */
  publicPdfUrl: string | null;
  sentAt: IsoDateTime | null;
}

// Notification preferences. The account popout offers them as self service.

/** Toggle for a notification kind (`GET/PUT /notifications/preferences`). */
export interface NotificationPreference {
  kind: string;
  enabled: boolean;
}

// OAuth grants and MCP setup. The account popout offers them as self service.

/** An active OAuth grant of the logged-in user. It is an agent or MCP token. */
export interface OAuthGrant {
  id: string;
  clientId: string;
  scope: string;
  createdAt: IsoDateTime | null;
  /** `null` means the access token never expires. Only a revocation ends it. */
  accessExpiresAt: IsoDateTime | null;
  refreshExpiresAt: IsoDateTime | null;
}

/** MCP setup snippet and metadata. GET /mcp/config. */
export interface McpSetup {
  mcpServers: Record<string, unknown>;
  baseUrl: string;
  clientId: string;
  scopesSupported: string[];
  install: string;
  note: string;
}

/** A scope row in the consent screen. `held` means the user holds the permission. */
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
