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

/** One maintained footer link: a label per locale plus its target. */
export interface PublicFooterLink {
  label: I18nMap;
  url: string;
}

/** A footer column of the branding: a heading and its links. */
export interface PublicFooterColumn {
  label: I18nMap;
  links: PublicFooterLink[];
}

/** Public branding config of the active site version. It needs no authentication.
 *  The type stays loose on purpose. The frontend reads only what it shows: the free
 *  texts (for example `applyInfo`), the app name and the footer. */
export interface PublicSiteConfig {
  version: number;
  /**
   * Hours a guest has to confirm the email before the platform discards the
   * application (admin setting `guest_application_settings.confirm_ttl_hours`).
   */
  confirmTtlHours?: number;
  /**
   * Lifetime of a new magic link in days (admin setting
   * `guest_application_settings.link_ttl_days`). `null`: the link does not expire.
   */
  linkTtlDays?: number | null;
  /** Upload limits of the wizard (Z4): one file, and all draft files of a draft token. */
  attachmentLimits?: AttachmentLimits | null;
  branding?: {
    /** Configured app name (language neutral). Empty falls back to i18n or the default. */
    appName?: string;
    /** Short name for the PWA icon. Empty falls back to the default. */
    appShortName?: string;
    /** Footer copyright line per locale. Empty falls back to the co-branding text. */
    copyright?: I18nMap;
    /** Footer legal links. Empty shows no legal link. */
    legalLinks?: PublicFooterLink[];
    /** Footer columns: a heading and its links each. Empty shows no column. */
    footerColumns?: PublicFooterColumn[];
    freetexts?: Partial<
      Record<
        | 'loginHint'
        | 'welcome'
        | 'support'
        | 'emailFooter'
        | 'applyInfo'
        | 'submittedInternal'
        | 'submittedExternal',
        I18nMap
      >
    >;
    /** Show the Gravatar images of the avatars (through the API proxy). Missing = on. */
    gravatarEnabled?: boolean;
  } | null;
}

/** Upload limits of the wizard (`attachmentLimits` of the public site config). */
export interface AttachmentLimits {
  maxFileBytes: number;
  maxDraftFiles: number;
  maxDraftBytes: number;
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
  /** Gremium id to the gremium permissions of the active role in that gremium
   *  (`session.manage`, `protocol.write`, `protocol.finalize`, `vote.manage`,
   *  `vote.cast`). */
  gremium_permissions?: Record<Uuid, string[]>;
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
  /**
   * Flow state UUIDs. The request repeats `state` once per value (A4), and the list keeps
   * the applications in any of these states.
   */
  state?: readonly string[];
  gremium?: Uuid;
  type?: Uuid;
  /** Cost center in the budget tree. The filter includes the subtree. */
  budget?: Uuid;
  q?: string;
  amountMin?: number;
  amountMax?: number;
  createdFrom?: string;
  createdTo?: string;
  /** `stateSince`: the time of the last status change, the date a row of "Meine Anträge"
   *  shows. */
  sort?: 'createdAt' | 'amount' | 'stateSince';
  order?: 'asc' | 'desc';
  /** Own applications only. It forces the owner filter even with `application.read`. */
  mine?: boolean;
  /**
   * Archived rows. `'false'` (the server default) hides them, `'true'` shows only those,
   * `'all'` shows both. A tri-state rather than a boolean, because "only the archived
   * ones" and "both" are different questions.
   */
  archived?: 'false' | 'true' | 'all';
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
  archivedAt?: IsoDateTime | null;
  /** Time of the last status change (A9). */
  stateSince?: IsoDateTime | null;
  /**
   * The `isPII` field keys that the server removed from `data` for this reader (O21).
   * Empty for a reader with the PII right.
   */
  hiddenKeys?: string[];
  /** Set when a person captured the application on behalf of the applicant (#11). */
  capture?: ApplicationCapture | null;
}

/**
 * `CaptureOut`. How an application captured on behalf of the applicant came in (#11).
 * `capturedBy` follows the actor rules of the timeline: the applicant view names the
 * Gremium instead of the member.
 */
export interface ApplicationCapture {
  capturedBy: ActorInfo | null;
  capturedAt: IsoDateTime;
  /** The date on which the application came in (`YYYY-MM-DD`). */
  receivedOn: string | null;
  /** The free-text intake channel ("Eingang"), for example "per PDF". */
  intake: string | null;
}

/** `ApplicantCandidateOut`. An account that the capture dialog offers as applicant. */
export interface ApplicantCandidate {
  id: Uuid;
  displayName: string | null;
  email: string | null;
}

/**
 * `OnBehalfCreate`. The body of `POST /applications/on-behalf` (#11). The applicant is
 * EITHER an account (`applicantPrincipalId`) OR a guest (`applicantName` and
 * `applicantEmail`).
 */
export interface OnBehalfApplication {
  typeId: Uuid;
  data: Record<string, unknown>;
  applicantPrincipalId?: Uuid | null;
  applicantName?: string | null;
  applicantEmail?: string | null;
  /** `YYYY-MM-DD`; the server defaults to today. */
  receivedOn?: string | null;
  intake?: string | null;
  lang: Lang;
  attachmentIds?: Uuid[];
  draftToken?: string | null;
}

/** `ApplicationListItem`. A list entry without `data` and without `applicant`. */
export interface ApplicationListItemWire {
  id: Uuid;
  typeId: Uuid;
  title?: string | null;
  state?: StateOutWire | null;
  gremiumId?: Uuid | null;
  amount?: string | null;
  currency?: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  archivedAt?: IsoDateTime | null;
  /** Time of the last status change (A9). */
  stateSince?: IsoDateTime | null;
}

/** `ApplicationCreated`. The 201 response of `POST /applications`. It holds only the id. */
export interface ApplicationCreatedWire {
  applicationId: Uuid;
}

/** Attendance status of a member in a meeting. `absent` means absent without an excuse. */
export type AttendanceStatus = 'present' | 'excused' | 'absent';

/** The statuses a member reports for the own record (Z2). Only the lead records `absent`. */
export type SelfAttendanceStatus = 'present' | 'excused';

/** A current gremium member. This is a protokollant candidate for a new meeting. */
export interface MeetingMember {
  principalId: Uuid;
  displayName: string | null;
  email: string | null;
  /** O20: the member holds `protocol.write` in the gremium and can keep the minutes. */
  canKeepProtocol?: boolean;
}

/** `AttendanceOut`. Attendance of a gremium member. GET/PUT/DELETE …/attendance. */
export interface Attendance {
  principalId: Uuid;
  displayName: string | null;
  email: string | null;
  /** `null` = not recorded yet ("open"). */
  status: AttendanceStatus | null;
  /** Who set the record. A `lead` record wins: the member cannot change it (O15). */
  source: 'self' | 'lead' | null;
  /**
   * The reason of an excuse. The server sends it only to the member and to the
   * meeting lead (`canWrite`). All other readers get `null`.
   */
  note: string | null;
  /** True if this row is the requesting user. It enables self-marking. */
  isSelf: boolean;
  /** O20: the member holds `protocol.write` in the gremium and can keep the minutes. */
  canKeepProtocol?: boolean;
  /**
   * The member has an own vote now (gremium permission `vote.cast`). Only such a member
   * can be substituted (O6). An older server leaves the flag out.
   */
  canVote?: boolean;
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

/**
 * `ActorOut`. The resolved actor of a timeline event, a version or a comment.
 * - `principal`: a member; `displayName` is the name (or the email).
 * - `applicant`: the applicant through the magic link; no name (PII, O21).
 * - `system`: an automatic action; `key` names the source (`deadlines`, `flow`, `auto`, …).
 * - `gremium`: the applicant view names the Gremium for a member (A12/O16).
 * - `deleted`: an unknown or anonymized account; no name, no id.
 */
export type ActorKind = 'principal' | 'applicant' | 'system' | 'gremium' | 'deleted';

export interface ActorInfo {
  kind: ActorKind;
  key?: string | null;
  displayName?: string | null;
  /** Only for `principal`: the account id, for the avatar. Never in the applicant view. */
  principalId?: Uuid | null;
}

/** `TimelineEventOut`. A status transition in the timeline. */
export interface TimelineEventOutWire {
  fromStateId?: Uuid | null;
  toStateId: Uuid;
  toState?: StateOutWire | null;
  /** Label of the fired transition (A3). Null for the creation and for a revert. */
  transitionLabel?: I18nMap | null;
  /** In the applicant view, the Gremium for every action of a member (A12). */
  actor?: string | null;
  /** The resolved actor. The UI renders this and never the raw `actor`. */
  actorInfo?: ActorInfo | null;
  at: IsoDateTime;
  note?: string | null;
  /** The vote whose close fired the event. Null in the applicant view. */
  voteId?: Uuid | null;
  /** A vote close fired the event, and the vote went with its meeting. */
  voteDeleted?: boolean;
}

export type CommentVisibility = 'internal' | 'public';
export type CommentAuthorKind = 'principal' | 'applicant';

/** `CommentOut`. The backend field names are `author`, `authorKind`, `visibility`, `at`. */
export interface CommentOutWire {
  id: Uuid;
  author?: string | null;
  authorKind: CommentAuthorKind;
  /** The resolved author. The UI renders this and never the raw `author`. */
  authorInfo?: ActorInfo | null;
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
  /** The transition carries an `addToNextSession` action into a vote state (A1), so a
   *  fire takes a `meetingId`. */
  addsToAgenda?: boolean;
  /** The gremium whose planned meetings the agenda dialog offers (A1). */
  agendaGremiumId?: Uuid | null;
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

/**
 * `VersionOut`. One submission version and its diff.
 *
 * The applicant view gets the metadata only (A11): `data` and `diff` are null, and
 * `changedKeys` lists the changed fields. A reader without the PII right gets no
 * `isPII` field in `data`, `diff` and `changedKeys` (O21).
 */
export interface VersionOutWire {
  version: number;
  data?: Record<string, unknown> | null;
  diff?: DataDiffWire | null;
  changedKeys?: string[];
  changedBy?: string | null;
  /** The resolved editor. The UI renders this and never the raw `changedBy`. */
  changedByInfo?: ActorInfo | null;
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
 * `DraftAttachmentOut` (files/schemas.py): 201 of `POST /apply/attachments` (Z4). The
 * attachment fields stay snake_case like `AttachmentOut`; the token fields are camelCase.
 */
export interface DraftAttachmentOutWire extends AttachmentOutWire {
  draftToken: string;
  draftExpiresAt: IsoDateTime;
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
  data: Record<string, unknown>;
  // Optional. For a logged-in user the backend takes the identity from the account.
  // For an anonymous submission the server requires these fields.
  applicantEmail?: string | null;
  applicantName?: string | null;
  lang: Lang;
  altcha?: string | null;
  /** Draft uploads of the wizard to bind (Z4). Needs `draftToken`. */
  attachmentIds?: Uuid[];
  /** The token of the draft uploads (Z4). */
  draftToken?: string | null;
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
  /**
   * The meeting whose agenda gets the application (A1). Only for a transition with
   * `addsToAgenda`; the meeting must be planned and belong to `agendaGremiumId`, else
   * the server answers 422 `agenda_meeting_invalid`.
   */
  meetingId?: Uuid | null;
  /** The new agenda item is not public (NÖ). Only with `meetingId`. */
  nonPublic?: boolean;
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
  /** The gremium that decides the current vote (snapshot on entry of a vote state). */
  voteGremiumId?: Uuid | null;
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
  /**
   * When it was archived, or null. A timestamp rather than a flag, so the view can say
   * WHEN without a second field.
   *
   * Archiving is not anonymisation: the record is complete and readable, it has only
   * left the working list. `be-privacy` owns the DSGVO erasure people confuse this with.
   */
  archivedAt: IsoDateTime | null;
  /** Time of the last status change (A9), for "since" on the status page. */
  stateSince?: IsoDateTime | null;
  /**
   * The `isPII` field keys that the server removed from `data` (O21). The edit form
   * leaves out these fields. A key that is only missing from `data` was never
   * answered, and the field stays editable.
   */
  hiddenKeys?: string[];
  /** Set when a person captured the application on behalf of the applicant (#11). */
  capture?: ApplicationCapture | null;
}

/**
 * A public, read-only link to one application.
 *
 * No separate wire type and no mapper: the payload is already camelCase and carries
 * nothing language-dependent, so a second shape would only be a copy that can drift.
 *
 * `url` holds the plaintext token and is therefore present ONLY in the response that
 * created the link. A listing returns it as null, because the server stored a hash and
 * cannot reconstruct the token — nor would it hand it back if it could.
 */
export interface ApplicationShareLink {
  id: Uuid;
  createdAt: IsoDateTime;
  expiresAt: IsoDateTime;
  /** Set once the link stops being honoured. A timestamp, so the list can say when. */
  revokedAt: IsoDateTime | null;
  createdBy: string | null;
  /** A note for whoever made it. Never shown on the public page. */
  label: string | null;
  url: string | null;
}

export interface ApplicationListItem {
  id: Uuid;
  typeId: Uuid;
  title: string | null;
  state: ApplicationState | null;
  gremiumId: Uuid | null;
  amount: string | null;
  currency: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  /** Set when the row is archived, so a combined list can mark it. */
  archivedAt: IsoDateTime | null;
  /** Time of the last status change (A9), for "waiting since". */
  stateSince?: IsoDateTime | null;
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
  /** Label of the fired transition (A3), resolved to the locale. */
  transitionLabel?: string | null;
  actor: string | null;
  actorInfo?: ActorInfo | null;
  at: IsoDateTime;
  note: string | null;
  /** The vote whose close fired the event, for the link to it. */
  voteId: Uuid | null;
  /** The vote that fired the event was deleted with its meeting. */
  voteDeleted: boolean;
}

/** Comment, frontend view. `isPublic` comes from `visibility`. */
export interface ApplicationComment {
  id: Uuid;
  author: string | null;
  authorKind: CommentAuthorKind;
  authorInfo?: ActorInfo | null;
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
  /**
   * The transition puts the application on the agenda of a meeting and leads into a
   * vote state (A1), so the server takes a chosen meeting. The detail and the row menu
   * open the agenda dialog for it, which asks for the meeting. A transition whose
   * action leads into a normal state is `false` here and fires as a plain transition;
   * the server action then picks the next planned meeting.
   */
  addsToAgenda: boolean;
  /** The gremium whose planned meetings the agenda dialog offers, or null. */
  agendaGremiumId: Uuid | null;
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
  /** Keys of the changed fields. The applicant view gets only these (A11). */
  changedKeys?: string[];
  changedBy: string | null;
  changedByInfo?: ActorInfo | null;
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

/** Frontend input for a new application. It maps to `ApplicationCreateBody`. */
export interface NewApplication {
  typeId: Uuid;
  data: Record<string, unknown>;
  // Null for a logged-in user. The backend takes the identity and the altcha itself.
  applicantEmail?: string | null;
  applicantName?: string | null;
  lang: Lang;
  altcha?: string | null;
  /** Draft uploads of the wizard to bind (Z4). */
  attachmentIds?: Uuid[];
  /** The token of the draft uploads; required with `attachmentIds`. */
  draftToken?: string | null;
}

/**
 * A draft upload of the wizard (Z4), frontend view: the attachment plus the field it
 * belongs to (`null` = the general block "Anhänge").
 */
export interface DraftAttachment extends Attachment {
  fieldKey: string | null;
}

/** The result of `POST /apply/attachments`: the draft and its (new) token. */
export interface DraftUpload {
  attachment: Attachment;
  draftToken: string;
  draftExpiresAt: IsoDateTime;
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
  /** Drives `visibleIf: has_budget`. Comes from the type, as the server's own check does. */
  hasBudget: boolean;
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
/** `draft`: planned, not open yet. `cancelled`: the application left the vote state by hand, so the vote stopped. */
export type VoteStatus = 'draft' | 'open' | 'closed' | 'cancelled';
export type VoteResult = 'passed' | 'rejected' | 'tie';

/** Quorum threshold. */
export interface Quorum {
  type: 'count' | 'percent';
  value: number;
}

/**
 * Vote configuration (`VoteConfig`). The backend `_CamelModel` sends the fields in
 * camelCase. The defaults mirror the Pydantic defaults: `abstainCountsQuorum` is
 * true, `secret` is false. The frontend never sets a tie break: a tie is a
 * rejection (O18).
 */
export interface VoteConfig {
  options: string[];
  majorityRule: MajorityRule;
  quorum?: Quorum | null;
  abstainCountsQuorum?: boolean;
  secret?: boolean;
  /** Admitted guests of a public meeting vote too: no quorum, majority of the cast votes. */
  guestsVote?: boolean;
}

/**
 * The own ballot of the caller in one vote (`MyBallot`). `choice` is the chosen
 * option. A secret vote keeps the choice apart from the identity, so there `choice`
 * is always `null` and only `cast` tells that the caller voted.
 */
export interface MyBallot {
  cast: boolean;
  choice: string | null;
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
  /** Turnout: the ballots cast so far. The server always sends it, also while the
   *  counts stay hidden. */
  voted?: number;
  /** The present members of the meeting (the reveal denominator). It is 0 for a vote
   *  without a meeting and for a closed vote. */
  present?: number;
  /** `counts` and `leading` are visible: the vote is closed, or it is open, not secret
   *  and every present member voted (a vote without a meeting is always visible).
   *  Otherwise `counts` is empty. */
  revealed?: boolean;
  /** Why a closed vote failed: `quorum` or `majority`. `null` while open, on a pass and
   *  on a tie. */
  failedReason?: 'quorum' | 'majority' | null;
  /** The present members and the admitted guests: live while open, fixed at the close.
   *  `null` for a vote that closed before public meetings existed. */
  presentMembers?: number | null;
  presentGuests?: number | null;
}

/**
 * Vote state and tally. GET /api/votes/{id} (`VoteOut`). It is a plain
 * `_CamelModel`, so the frontend uses it 1:1 as a view model. It carries no i18n
 * label. The options are raw keys. The frontend translates them through
 * `vote.option.*`.
 */
export interface Vote {
  id: Uuid;
  /** `null` marks a motion on a free-text agenda item, with no application. */
  applicationId: Uuid | null;
  /** The meeting that holds the vote. `null` marks a standalone (async) vote.
   *  A meeting-bound vote is deleted through its meeting, never through
   *  `DELETE /votes/{id}` (that route answers 409). */
  meetingId?: Uuid | null;
  /** The agenda item of a meeting vote. The page reads its number ("TOP 3") from the
   *  agenda. */
  agendaItemId?: Uuid | null;
  /** The motion of a meeting vote. A standalone vote often has none. */
  question?: string | null;
  eligibleGroup: string;
  config: VoteConfig;
  status: VoteStatus;
  opensAt: IsoDateTime | null;
  /** The planned end of the cast window (a deadline), not the real end. */
  closesAt: IsoDateTime | null;
  result: VoteResult | null;
  secret: boolean;
  /** Copies of `config.majorityRule` and `config.quorum` for the vote card. */
  majorityRule?: MajorityRule;
  quorum?: Quorum | null;
  /** The real moment when the vote opened. */
  openedAt?: IsoDateTime | null;
  /** The real moment when the vote ended (close or cancel). `null` while it runs. */
  closedAt?: IsoDateTime | null;
  tally: Tally;
  /** The own ballot of the caller. Only `GET /votes/{id}` sets it. */
  myBallot?: MyBallot | null;
  /** Admitted guests vote too: no quorum, the majority of the cast votes decides. */
  guestsVote?: boolean;
  /** The caller cast the ballot of a delegator in this vote. Only `GET /votes/{id}`
   *  sets it. */
  representedCast?: boolean;
  /** The caller may open, close, cancel and delete the vote: the admin role, or the
   *  gremium permission `vote.manage` or `session.manage` in the gremium of the vote.
   *  Only `GET /votes/{id}` sets it. */
  canManage?: boolean;
  /** The caller may cast an own ballot: the gremium permission `vote.cast` in the
   *  gremium of the vote, in a browser session. A delegated ballot has its own check.
   *  Only `GET /votes/{id}` sets it. */
  canCast?: boolean;
}

/**
 * One row of the vote list (`GET /votes`, `VoteListItem`). The row carries no tally;
 * `GET /votes/{id}` reads it. `myBallot` and `canCast` are the own ballot state of the
 * caller: a secret vote gives only `cast`, never the choice. `meetingTitle` and
 * `agendaPosition` (the number of the agenda item, "TOP 3") are `null` for a vote
 * without a meeting. `gremiumName` is `null` when the vote names no gremium.
 */
export interface VoteListItem {
  id: Uuid;
  question: string | null;
  status: VoteStatus;
  result: VoteResult | null;
  secret: boolean;
  applicationId: Uuid | null;
  meetingId: Uuid | null;
  meetingTitle: string | null;
  agendaItemId: Uuid | null;
  agendaPosition: number | null;
  gremiumId: Uuid | null;
  gremiumName: string | null;
  createdAt: IsoDateTime;
  openedAt: IsoDateTime | null;
  closedAt: IsoDateTime | null;
  /** The planned end of the cast window, not the real end. */
  closesAt: IsoDateTime | null;
  canCast: boolean;
  myBallot: MyBallot;
}

/**
 * The filters of `GET /votes`. `status` repeats; without it the server leaves out the
 * drafts. `q` searches the question and the meeting title.
 */
export interface VoteListQuery {
  status?: VoteStatus[];
  gremiumId?: Uuid;
  q?: string;
  limit?: number;
  offset?: number;
}

/** Response to an accepted ballot. POST /api/votes/{id}/ballot. A ballot never
 *  changes after the cast: a second cast gives 409 `already_voted`. */
export interface BallotResult {
  status: 'cast';
}

/**
 * Result of `POST /votes/{id}/close` (`VoteClosed`). The close always ends the vote.
 * `branchFired` is false when the pass or fail transition of the application did not
 * fire (the guard failed, or the state has no such transition). A person must then
 * move the application by hand.
 */
export interface VoteClosed {
  id: Uuid;
  meetingId?: Uuid | null;
  applicationId?: Uuid | null;
  result: VoteResult;
  tally: Tally;
  closedAt?: IsoDateTime | null;
  firedTransitionId?: Uuid | null;
  newStateId?: Uuid | null;
  branchFired: boolean;
}

// Meetings and protocol. The wire form is camelCase (`_CamelModel`).

/** Meeting status. The backend enum is `planned|live|closed`. */
export type MeetingStatus = 'planned' | 'live' | 'closed';
/** `draft`: planned, not open yet. `cancelled`: the application left the vote state by hand, so the vote stopped. */
export type MeetingVoteStatus = 'draft' | 'open' | 'closed' | 'cancelled';

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
  majorityRule?: MajorityRule;
  secret?: boolean;
  quorum?: Quorum | null;
  /** The real open time and the real end time (close or cancel). */
  openedAt?: IsoDateTime | null;
  closedAt?: IsoDateTime | null;
  /** The own ballot of the caller. A secret vote gives only `cast`. */
  myBallot?: MyBallot | null;
  /** The caller cast the ballot of a delegator in this vote. */
  representedCast?: boolean;
  /** Admitted guests vote too (public meeting): no quorum. */
  guestsVote?: boolean;
  /** Present members and admitted guests (live while open, fixed at the close). */
  presentMembers?: number | null;
  presentGuests?: number | null;
}

/** `MeetingOut`. Meeting state and votes. GET /meetings/{id}. */
/**
 * `KeeperPeriodOut`. One period of a protocol keeper (Z3, A13). `fromAt` is `null`
 * for the planned handover, `toAt` is `null` while the period runs. The positions
 * are 1-based numbers in the current agenda order, `null` without an item.
 */
export interface KeeperPeriod {
  principalId: Uuid;
  name: string | null;
  fromAt: IsoDateTime | null;
  toAt: IsoDateTime | null;
  fromAgendaItemId: Uuid | null;
  toAgendaItemId: Uuid | null;
  fromPosition: number | null;
  toPosition: number | null;
}

/** How the minutes change hands: at once, or with the next agenda item. */
export type HandoverMode = 'now' | 'next_item';

export interface MeetingOutWire {
  id: Uuid;
  title: string;
  date?: string | null;
  startTime?: string | null;
  endTime?: string | null;
  status: MeetingStatus;
  activeApplicationId?: Uuid | null;
  /** The agenda item the room handles now. */
  currentAgendaItemId?: Uuid | null;
  /** Number (1-based, in agenda order) and title of the current agenda item. */
  currentAgendaItem?: CurrentAgendaItem | null;
  /** Number of items on the agenda. */
  agendaItemCount?: number;
  /** The real start. `null` before the start and for an older meeting. */
  startedAt?: IsoDateTime | null;
  /** The close sets it. */
  closedAt?: IsoDateTime | null;
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
  /** Finalize and send the protocol: write access plus the gremium permission
   *  `protocol.finalize`. */
  canFinalize?: boolean;
  /** The periods of the protocol keepers, running and ended, in time order. */
  keeperPeriods?: KeeperPeriod[];
  /** The handover planned for the next agenda item. */
  plannedHandover?: KeeperPeriod | null;
  /** Public participation over a QR code is on. */
  publicJoin?: boolean;
  /** Admitted guests vote (`vote`) or only follow the meeting (`watch`). */
  guestsMode?: GuestsMode;
  /** The join code (`7KQ4MP`); the server sends it to the meeting lead only. */
  joinCode?: string | null;
  /** The guests admitted now. */
  admittedGuests?: number;
  /** The open join requests; the meeting lead only, else 0. */
  pendingGuests?: number;
  /** Public participation is possible: only a gremium without a quorum allows it. */
  publicJoinAllowed?: boolean;
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
  /** The protocol is held back from the public protocol page. */
  publicWithheld?: boolean;
  /** The gremium publishes its final protocols on the public protocol page. */
  gremiumProtocolsPublic?: boolean;
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
  /** Public participation over a QR code. */
  publicJoin?: boolean;
  guestsMode?: GuestsMode;
}

/** Body for `PATCH /meetings/{id}`. Status, active application, date or protokollant. */
export interface MeetingPatchBody {
  status?: MeetingStatus;
  activeApplicationId?: Uuid | null;
  /** The agenda item the room handles now. `null` clears it. Protokollant or session lead. */
  currentAgendaItemId?: Uuid | null;
  /** New title (1 to 200 characters). Planned or live only: a closed meeting gives 409. */
  title?: string;
  /** Planned meeting date (`YYYY-MM-DD`). Use it to schedule a planned meeting. */
  date?: string | null;
  /** Planned time (`HH:mm`). */
  startTime?: string | null;
  /** Planned end time (`HH:mm`). */
  endTime?: string | null;
  /** (Re)assign the protokollant. */
  protokollantId?: Uuid | null;
  /** Public participation on or off. Off voids the requests and ends the guests. */
  publicJoin?: boolean;
  /** Guests vote or only follow. `watch` gives 409 `guest_vote_open` while a guest vote runs. */
  guestsMode?: GuestsMode;
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
  /** The own ballot of the caller. A secret vote gives only `cast`. `null` when the
   *  server sent none (for example a broadcast). */
  myBallot?: MyBallot | null;
  /** The rules of the vote, for the vote card (A5). A vote that a WS event added
   *  before the next GET has none of them. */
  majorityRule?: MajorityRule;
  secret?: boolean;
  quorum?: Quorum | null;
  /** The real open time, and the real end time (close or cancel). */
  openedAt?: IsoDateTime | null;
  closedAt?: IsoDateTime | null;
  /** Admitted guests vote too: no quorum, majority of the cast votes. */
  guestsVote?: boolean;
  /** Present members and admitted guests ("19 Mitglieder + 7 Gäste anwesend"). */
  presentMembers?: number | null;
  presentGuests?: number | null;
}

/** The agenda item the room handles now, as `MeetingOut.currentAgendaItem` sends it. */
export interface CurrentAgendaItem {
  /** 1-based number in the agenda order ("TOP 3"). */
  position: number;
  title: string | null;
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
  /** The agenda item the room handles now ("Jetzt"). Followers and the beamer follow it. */
  currentAgendaItemId: Uuid | null;
  /** Number (1-based, in agenda order) and title of the current agenda item. */
  currentAgendaItem?: CurrentAgendaItem | null;
  /** Number of items on the agenda. */
  agendaItemCount?: number;
  /** The real start. The start sets it once. `null` before the start, and for a
   *  meeting that started before the field existed: show the planned start then. */
  startedAt?: IsoDateTime | null;
  /** The close sets it. */
  closedAt?: IsoDateTime | null;
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
  /** Finalize and send the protocol: write access plus the gremium permission
   *  `protocol.finalize`. */
  canFinalize: boolean;
  /** The periods of the protocol keepers, running and ended, in time order (Z3). */
  keeperPeriods: KeeperPeriod[];
  /** The handover planned for the next agenda item, or `null`. */
  plannedHandover: KeeperPeriod | null;
  /** Public participation over a QR code is on. */
  publicJoin: boolean;
  /** Admitted guests vote or only follow the meeting. */
  guestsMode: GuestsMode;
  /** The join code, for the meeting lead only (`null` for everybody else). */
  joinCode: string | null;
  /** The guests admitted now. */
  admittedGuests: number;
  /** The open join requests (meeting lead only, else 0). */
  pendingGuests: number;
  /** Public participation is possible: only a gremium without a quorum allows it. */
  publicJoinAllowed: boolean;
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
  /** Held back from the public protocol page (only matters for a public gremium). */
  publicWithheld?: boolean;
  /** The gremium publishes its final protocols on the public protocol page. */
  gremiumProtocolsPublic?: boolean;
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
  /**
   * Every new token expires (90 days at most). `null` comes only from a token of the time
   * before the cap; the pages show a dash, never "Läuft nie ab".
   */
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

/** What kind of record a search hit points at. Stable keys, never translated text. */
export type SearchKind =
  | 'application'
  | 'meeting'
  | 'invoice'
  | 'expense'
  | 'budget'
  | 'gremium'
  | 'principal';

/**
 * One row of the global search (`GET /api/search`).
 *
 * Deliberately flat: the palette renders a line, a line under it, and somewhere to go,
 * without knowing the shape of an application, an invoice or a meeting. `url` is always
 * an app-relative route the client has.
 */
export interface SearchHit {
  kind: SearchKind;
  id: string;
  title: string;
  subtitle: string | null;
  url: string;
  /** Applications only. The row badges it, so an archived hit is not read as current. */
  archived?: boolean;
}

/** Everything found for one query, in one round trip. */
export interface SearchResults {
  hits: SearchHit[];
  /** At least one source had more matches than its cap, so this is not everything. */
  truncated: boolean;
  /** Sources that errored. The search degrades rather than returning nothing. */
  failed: string[];
}

// Public meeting with QR code (#17).

/** Admitted guests vote (`vote`) or only follow the meeting (`watch`). */
export type GuestsMode = 'vote' | 'watch';

/** The state of a join request or of a guest. */
export type GuestStatus = 'pending' | 'admitted' | 'rejected' | 'removed' | 'left';

/** `MeetingGuest`: one join request or guest, for the meeting lead. */
export interface MeetingGuest {
  id: Uuid;
  /** The pseudonym number ("Gast 3"), 1-based per meeting. */
  number: number;
  /** `null` once pseudonymized (left, withdrawn, protocol final): show "Gast {number}". */
  displayName: string | null;
  /** `expired` comes only with a `guest_updated` event: the row is gone (a voided request). */
  status: GuestStatus | 'expired';
  requestedAt: IsoDateTime;
  decidedAt: IsoDateTime | null;
  decidedByName: string | null;
  admittedAt: IsoDateTime | null;
}

/** The QR matrix without a quiet zone: `size` rows of `size` characters `0`/`1`. */
export interface QrMatrix {
  size: number;
  rows: string[];
}

/** `JoinLink`: the join code, the absolute join URL and its QR matrix. */
export interface JoinLink {
  joinCode: string;
  joinUrl: string;
  qr: QrMatrix;
}

/** `PublicMeetingHead`: what the join page shows before the admission. */
export interface PublicMeetingHead {
  code: string;
  title: string;
  gremiumName: string | null;
  date: string | null;
  startTime: string | null;
  status: MeetingStatus;
  startedAt: IsoDateTime | null;
  guestsMode: GuestsMode;
}

/** One agenda item of the guest view. A non-public item carries its title, never a body. */
export interface GuestAgendaItem {
  id: Uuid;
  position: number;
  title: string | null;
  kind: 'application' | 'freetext';
  nonPublic: boolean;
  body: string | null;
}

/** One vote of a public item, as an admitted guest sees it. */
export interface GuestVote {
  id: Uuid;
  agendaItemId: Uuid | null;
  question: string | null;
  options: string[];
  status: 'open' | 'closed';
  secret: boolean;
  majorityRule: MajorityRule;
  guestsVote: boolean;
  quorum: Quorum | null;
  openedAt: IsoDateTime | null;
  closedAt: IsoDateTime | null;
  result: VoteResult | null;
  failedReason: 'quorum' | 'majority' | null;
  tally: {
    counts: Record<string, number>;
    voted: number;
    present: number;
    revealed: boolean;
    leading: string | null;
    presentMembers: number | null;
    presentGuests: number | null;
  };
  myBallot: { cast: boolean; choice: string | null };
  canCast: boolean;
}

/** The participant view of an admitted guest. */
export interface GuestView {
  currentAgendaItemId: Uuid | null;
  presentMembers: number;
  admittedGuests: number;
  agenda: GuestAgendaItem[];
  votes: GuestVote[];
}

/** `GuestMe`: the own request or participation of this device. */
export interface GuestMe {
  guestId: Uuid;
  number: number;
  displayName: string | null;
  status: GuestStatus;
  /** Seconds until a new request is possible (rejected, removed), else `null`. */
  retryAfter: number | null;
  meeting: PublicMeetingHead;
  view: GuestView | null;
}

/** `GET /gremien/{id}/meeting-defaults`: what a new meeting of the gremium allows. */
export interface MeetingDefaults {
  publicJoinAllowed: boolean;
  quorumPercent: number | null;
}
