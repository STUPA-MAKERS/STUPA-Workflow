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

/** A person on a card, a ticket, a note or an event. null/null = deleted person. */
export interface PersonRef {
  readonly principalId: Uuid | null;
  /** The name, else the account e-mail, else null. */
  readonly displayName: string | null;
}

/**
 * A content language: `de`, `en` or the BCP 47 code of an extra language (`fr`, `pt-BR`). A
 * text falls back along the chain of the language (`fr` → `en` → `de`).
 */
export type Lang = string;

/** Configurable multilingual text (`*_i18n` JSONB). */
export type I18nMap = Readonly<Record<string, string>>;

/** One maintained footer link: a label per locale plus its target. */
export interface PublicFooterLink {
  readonly label: I18nMap;
  readonly url: string;
}

/** Public branding config of the active site version. It needs no authentication.
 *  The type stays loose on purpose. The frontend reads only what it shows: the free
 *  texts (for example `applyInfo`), the app name and the footer. */
export interface PublicSiteConfig {
  readonly version: number;
  /**
   * Hours a guest has to confirm the email before the platform discards the
   * application (admin setting `guest_application_settings.confirm_ttl_hours`).
   */
  readonly confirmTtlHours?: number;
  /**
   * Lifetime of a new magic link in days (admin setting
   * `guest_application_settings.link_ttl_days`). `null`: the link does not expire.
   */
  readonly linkTtlDays?: number | null;
  /** Upload limits of the wizard: one file, and all draft files of a draft token. */
  readonly attachmentLimits?: AttachmentLimits | null;
  readonly branding?: {
    /** Configured app name (language neutral). Empty falls back to i18n or the default. */
    readonly appName?: string;
    /** Short name for the PWA icon. Empty falls back to the default. */
    readonly appShortName?: string;
    /** Footer copyright line per locale. Empty falls back to the co-branding text. */
    readonly copyright?: I18nMap;
    /** Footer legal links. Empty shows no legal link. */
    readonly legalLinks?: readonly PublicFooterLink[];
    readonly freetexts?: Readonly<
      Partial<
        Record<
          | 'loginHint'
          | 'welcome'
          | 'support'
          | 'emailFooter'
          | 'applyInfo'
          | 'submittedInternal'
          | 'submittedExternal'
          | 'accessibilityStatement',
          I18nMap
        >
      >
    >;
    /** Show the Gravatar images of the avatars (through the API proxy). Missing = on. */
    readonly gravatarEnabled?: boolean;
    /** The accent colour of the app (`#rrggbb`). Missing or null = the built-in accent. */
    readonly accentColor?: string | null;
    /** The uploaded logos by slot. A missing slot shows the built-in logo. */
    readonly logos?: Readonly<
      Partial<Record<'wordmark' | 'imagemark' | 'favicon', { readonly url: string }>>
    >;
  } | null;
  /** The handbook link of the help menu. Missing on an older server. */
  readonly help?: { readonly wikiUrl: string };
  /** Visitors without a session may send a ticket ("Problem melden"). */
  readonly tickets?: { readonly publicEnabled: boolean };
}

/** Upload limits of the wizard (`attachmentLimits` of the public site config). */
export interface AttachmentLimits {
  readonly maxFileBytes: number;
  readonly maxDraftFiles: number;
  readonly maxDraftBytes: number;
}

/** Uniform problem object (close to RFC 9457). */
export interface ProblemDetail {
  readonly type: string;
  readonly title: string;
  readonly status: number;
  readonly code: string;
  readonly detail?: string;
  readonly errors?: { readonly field: string; readonly msg: string }[];
  readonly traceId?: string;
}

/**
 * Principal (OIDC) with roles, permissions and groups. GET /api/auth/me.
 *
 * The field names mirror the backend `MeOut` 1:1. `MeOut` is a plain `BaseModel`
 * and not a `_CamelModel`, so `display_name` keeps its snake_case name.
 */
/** Small gremium reference. It names one membership of a principal. */
export interface GremiumRef {
  readonly id: Uuid;
  readonly name: string;
  readonly slug: string;
}

export interface Principal {
  readonly sub: Uuid;
  readonly email?: string | null;
  readonly display_name?: string | null;
  readonly roles: readonly string[];
  readonly permissions: readonly string[];
  readonly groups: readonly string[];
  /** Gremien the principal belongs to. This drives the "My gremien" view. */
  readonly gremien?: GremiumRef[];
  /** Gremien the principal manages through a gremium role with `session.manage`. */
  readonly session_manage_gremien?: readonly Uuid[];
  /** Gremium id to the gremium permissions of the active role in that gremium
   *  (`session.manage`, `protocol.write`, `protocol.finalize`, `vote.manage`,
   *  `vote.cast`). */
  readonly gremium_permissions?: Readonly<Record<Uuid, readonly string[]>>;
  /** At least one cost center belongs to a gremium of this principal. */
  readonly has_scoped_budget_view?: boolean;
  /** The principal is in at least one substitute pool. The meeting timeline shows. */
  readonly in_substitute_pool?: boolean;
  /** The principal reported a ticket that is not anonymized: the tab "Tickets" shows. */
  readonly has_reported_tickets?: boolean;
}

/** Response of POST /api/auth/logout. An RP-initiated OIDC logout URL, or null. */
export interface LogoutOut {
  readonly logout_url: string | null;
}

/** Uniform list envelope (offset paging). */
export interface Page<T> {
  readonly items: readonly T[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface ApplicationListQuery {
  /**
   * Flow state UUIDs. The request repeats `state` once per value, and the list keeps
   * the applications in any of these states.
   */
  readonly state?: readonly string[];
  readonly gremium?: Uuid;
  readonly type?: Uuid;
  /** Cost center in the budget tree. The filter includes the subtree. */
  readonly budget?: Uuid;
  readonly q?: string;
  readonly amountMin?: number;
  readonly amountMax?: number;
  readonly createdFrom?: string;
  readonly createdTo?: string;
  /** `stateSince`: the time of the last status change, the date a row of "Meine Anträge"
   *  shows. */
  readonly sort?: 'createdAt' | 'amount' | 'stateSince';
  readonly order?: 'asc' | 'desc';
  /** Own applications only. It forces the owner filter even with `application.read`. */
  readonly mine?: boolean;
  /**
   * Archived rows. `'false'` (the server default) hides them, `'true'` shows only those,
   * `'all'` shows both. A tri-state rather than a boolean, because "only the archived
   * ones" and "both" are different questions.
   */
  readonly archived?: 'false' | 'true' | 'all';
  readonly limit?: number;
  readonly offset?: number;
}

/** `StateOut`. The `label` is an i18n map. */
export interface StateOutWire {
  readonly id: Uuid;
  readonly key: string;
  readonly label: I18nMap;
  /** Optional display color of the state badge, as hex. */
  readonly color?: string | null;
  readonly editAllowed: boolean;
  /** State kind: normal|vote. */
  readonly kind?: string;
}

/** `ApplicantOut`. It holds PII. The backend fills it only for an authorized reader. */
export interface ApplicantOutWire {
  readonly email?: string | null;
  readonly name?: string | null;
  readonly anonymized: boolean;
}

/** `ApplicationOut`. The application detail. */
export interface ApplicationOutWire {
  readonly id: Uuid;
  readonly typeId: Uuid;
  readonly state?: StateOutWire | null;
  readonly gremiumId?: Uuid | null;
  readonly budgetId?: Uuid | null;
  readonly fiscalYearId?: Uuid | null;
  readonly amount?: string | null;
  readonly currency?: string | null;
  readonly data: Readonly<Record<string, unknown>>;
  readonly version: number;
  readonly lang?: string | null;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
  readonly applicant?: ApplicantOutWire | null;
  readonly canEdit?: boolean;
  readonly canEditLocked?: boolean;
  readonly isOwner?: boolean;
  readonly archivedAt?: IsoDateTime | null;
  /** Time of the last status change. */
  readonly stateSince?: IsoDateTime | null;
  /**
   * The `isPII` field keys that the server removed from `data` for this reader.
   * Empty for a reader with the PII right.
   */
  readonly hiddenKeys?: readonly string[];
  /** Set when a person captured the application on behalf of the applicant. */
  readonly capture?: ApplicationCapture | null;
  /** The amount that the cost center binds. `null` means as requested. */
  readonly approvedAmount?: string | null;
  /** The valid decision, or `null` before one. */
  readonly decision?: ApplicationDecision | null;
}

/**
 * `DecisionIn`. A decision proposal (approval with deviations): the approved amount
 * and the conditions. The body of a vote (`proposal`) and of a transition (`decision`).
 */
export interface DecisionProposal {
  /** Decimal string with a dot (`"800.00"`). `null` means as requested. */
  readonly approvedAmount: string | null;
  /** The conditions (Auflagen), at most 20, each 1 to 1000 characters. */
  readonly conditions: readonly string[];
}

/**
 * `DecisionOut`. The valid decision of an application, or `null` before one. The
 * applicant view names the Gremium only: `voteId`, `meetingTitle` and `agendaPosition`
 * are `null` there.
 */
export interface ApplicationDecision {
  readonly requestedAmount: string | null;
  /** `null` means as requested. */
  readonly approvedAmount: string | null;
  readonly amountDeviates: boolean;
  readonly conditions: readonly string[];
  readonly decidedAt: IsoDateTime;
  readonly voteId: Uuid | null;
  readonly gremiumName: string | null;
  readonly meetingTitle: string | null;
  readonly agendaPosition: number | null;
}

/** `TimelineDecisionOut`. The decision that a status change carried. */
export interface TimelineDecision {
  readonly requestedAmount: string | null;
  readonly approvedAmount: string | null;
  readonly amountDeviates: boolean;
  readonly conditionCount: number;
}

/**
 * `CaptureOut`. How an application captured on behalf of the applicant came in.
 * `capturedBy` follows the actor rules of the timeline: the applicant view names the
 * Gremium instead of the member.
 */
export interface ApplicationCapture {
  readonly capturedBy: ActorInfo | null;
  readonly capturedAt: IsoDateTime;
  /** The date on which the application came in (`YYYY-MM-DD`). */
  readonly receivedOn: string | null;
  /** The free-text intake channel ("Eingang"), for example "per PDF". */
  readonly intake: string | null;
}

/** `ApplicantCandidateOut`. An account that the capture dialog offers as applicant. */
export interface ApplicantCandidate {
  readonly id: Uuid;
  readonly displayName: string | null;
  readonly email: string | null;
}

/**
 * `OnBehalfCreate`. The body of `POST /applications/on-behalf`. The applicant is
 * EITHER an account (`applicantPrincipalId`) OR a guest (`applicantName` and
 * `applicantEmail`).
 */
export interface OnBehalfApplication {
  readonly typeId: Uuid;
  readonly data: Readonly<Record<string, unknown>>;
  readonly applicantPrincipalId?: Uuid | null;
  readonly applicantName?: string | null;
  readonly applicantEmail?: string | null;
  /** `YYYY-MM-DD`; the server defaults to today. */
  readonly receivedOn?: string | null;
  readonly intake?: string | null;
  readonly lang: Lang;
  readonly attachmentIds?: readonly Uuid[];
  readonly draftToken?: string | null;
  /** The Vorgänger of a Folgeantrag; the capturing person must read it. */
  readonly predecessorId?: Uuid | null;
}

/** `LinkedApplicationOut`. A Vorgänger or a Folgeantrag as the reader may see it. */
export interface LinkedApplicationWire {
  readonly id: Uuid;
  readonly title?: string | null;
  readonly state?: StateOutWire | null;
  readonly createdAt: IsoDateTime;
  readonly archived?: boolean;
}

/** `LinkEventOut`. One change of the Vorgänger link. */
export interface LinkEventWire {
  readonly action: 'set' | 'removed';
  readonly at: IsoDateTime;
  readonly actorInfo?: ActorInfo | null;
  readonly predecessor?: LinkedApplicationWire | null;
}

/** `ApplicationLinksOut`. The Vorgänger, the Folgeanträge and the link history. */
export interface ApplicationLinksWire {
  readonly predecessor?: LinkedApplicationWire | null;
  readonly successors?: readonly LinkedApplicationWire[];
  readonly events?: readonly LinkEventWire[];
}

/** `ApplicationPrefillOut`. The answers of a Vorgänger that fit the current form. */
export interface ApplicationPrefill {
  readonly typeId: Uuid;
  readonly data: Readonly<Record<string, unknown>>;
}

/** `ApplicationListItem`. A list entry without `data` and without `applicant`. */
export interface ApplicationListItemWire {
  readonly id: Uuid;
  readonly typeId: Uuid;
  readonly title?: string | null;
  readonly state?: StateOutWire | null;
  readonly gremiumId?: Uuid | null;
  readonly amount?: string | null;
  /** The approved amount. `null` means as requested. */
  readonly approvedAmount?: string | null;
  readonly currency?: string | null;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
  readonly archivedAt?: IsoDateTime | null;
  /** Time of the last status change. */
  readonly stateSince?: IsoDateTime | null;
}

/** `ApplicationCreated`. The 201 response of `POST /applications`. It holds only the id. */
export interface ApplicationCreatedWire {
  readonly applicationId: Uuid;
}

/** Attendance status of a member in a meeting. `absent` means absent without an excuse. */
export type AttendanceStatus = 'present' | 'excused' | 'absent';

/** The statuses a member reports for the own record. Only the lead records `absent`. */
export type SelfAttendanceStatus = 'present' | 'excused';

/** A current gremium member. This is a protokollant candidate for a new meeting. */
export interface MeetingMember {
  readonly principalId: Uuid;
  readonly displayName: string | null;
  readonly email: string | null;
  /** The member holds `protocol.write` in the gremium and can keep the minutes. */
  readonly canKeepProtocol?: boolean;
}

/** `AttendanceOut`. Attendance of a gremium member. GET/PUT/DELETE …/attendance. */
export interface Attendance {
  readonly principalId: Uuid;
  readonly displayName: string | null;
  readonly email: string | null;
  /** `null` = not recorded yet ("open"). */
  readonly status: AttendanceStatus | null;
  /** Who set the record. A `lead` record wins: the member cannot change it. */
  readonly source: 'self' | 'lead' | null;
  /**
   * The reason of an excuse. The server sends it only to the member and to the
   * meeting lead (`canWrite`). All other readers get `null`.
   */
  readonly note: string | null;
  /** True if this row is the requesting user. It enables self-marking. */
  readonly isSelf: boolean;
  /** The member holds `protocol.write` in the gremium and can keep the minutes. */
  readonly canKeepProtocol?: boolean;
  /**
   * The member has an own vote now (gremium permission `vote.cast`). Only such a member
   * can be substituted. An older server leaves the flag out.
   */
  readonly canVote?: boolean;
}

/** `AgendaItemOut`. An agenda item holds a linked application or free text. */
export interface AgendaItem {
  readonly id: Uuid;
  /** `null` for a free-text agenda item (no application). */
  readonly applicationId: Uuid | null;
  /** The to-do card that the item was made from, or `null`. */
  readonly todoId?: Uuid | null;
  /** The own title of the item, else the title of its application. */
  readonly title: string | null;
  /** The title of the application. `null` for a free-text item. */
  readonly applicationTitle?: string | null;
  /** Markdown text of this agenda item. Each item has its own editor. */
  readonly body?: string | null;
  readonly position: number;
  /** Non-public. The public protocol PDF redacts this agenda item. */
  readonly nonPublic?: boolean;
  /** The done mark ("TOP abhaken"): the time of the tick, or `null`. Set by hand only. */
  readonly doneAt?: string | null;
  readonly stateLabel?: I18nMap | null;
  /** The requested amount of the application, for the decision proposal. */
  readonly amount?: string | null;
}

/** `AssignableApplicationOut`. An application in a vote state that is not on the agenda. */
export interface AssignableApplication {
  readonly applicationId: Uuid;
  readonly title: string | null;
  readonly stateLabel?: I18nMap | null;
}

/** `AltchaChallengeOut`. A server-signed proof-of-work challenge. GET /altcha/challenge. */
export interface AltchaChallenge {
  readonly algorithm: string;
  readonly challenge: string;
  readonly salt: string;
  readonly signature: string;
  readonly maxnumber: number;
}

/**
 * `ActorOut`. The resolved actor of a timeline event, a version or a comment.
 * - `principal`: a member; `displayName` is the name (or the email).
 * - `applicant`: the applicant through the magic link; no name (PII).
 * - `system`: an automatic action; `key` names the source (`deadlines`, `flow`, `auto`, …).
 * - `gremium`: the applicant view names the Gremium for a member.
 * - `deleted`: an unknown or anonymized account; no name, no id.
 */
export type ActorKind = 'principal' | 'applicant' | 'system' | 'gremium' | 'deleted';

export interface ActorInfo {
  readonly kind: ActorKind;
  readonly key?: string | null;
  readonly displayName?: string | null;
  /** Only for `principal`: the account id, for the avatar. Never in the applicant view. */
  readonly principalId?: Uuid | null;
}

/** `TimelineEventOut`. A status transition in the timeline. */
export interface TimelineEventOutWire {
  readonly fromStateId?: Uuid | null;
  readonly toStateId: Uuid;
  readonly toState?: StateOutWire | null;
  /** Label of the fired transition. Null for the creation and for a revert. */
  readonly transitionLabel?: I18nMap | null;
  /** In the applicant view, the Gremium for every action of a member. */
  readonly actor?: string | null;
  /** The resolved actor. The UI renders this and never the raw `actor`. */
  readonly actorInfo?: ActorInfo | null;
  readonly at: IsoDateTime;
  readonly note?: string | null;
  /** The vote whose close fired the event. Null in the applicant view. */
  readonly voteId?: Uuid | null;
  /** A vote close fired the event, and the vote went with its meeting. */
  readonly voteDeleted?: boolean;
  /** The decision that this status change carried. */
  readonly decision?: TimelineDecision | null;
}

export type CommentVisibility = 'internal' | 'public';
export type CommentAuthorKind = 'principal' | 'applicant';

/** `CommentOut`. The backend field names are `author`, `authorKind`, `visibility`, `at`. */
export interface CommentOutWire {
  readonly id: Uuid;
  readonly author?: string | null;
  readonly authorKind: CommentAuthorKind;
  /** The resolved author. The UI renders this and never the raw `author`. */
  readonly authorInfo?: ActorInfo | null;
  readonly body: string;
  readonly visibility: CommentVisibility;
  readonly at: IsoDateTime;
  /** True if the viewer wrote this comment. The server decides. It aligns the chat. */
  readonly isOwn?: boolean;
  /** When the text was last changed; null or absent for a comment never edited. */
  readonly editedAt?: IsoDateTime | null;
  /** The files of the comment, oldest first; absent on an older server. */
  readonly attachments?: readonly MessageAttachment[];
  /** The people the comment mentions; empty in the applicant view, absent on an older server. */
  readonly mentions?: readonly PersonRef[];
}

/** `ApplicationTypeListItem`. */
export interface ApplicationTypeListItemWire {
  readonly id: Uuid;
  readonly name: string;
  readonly hasBudget: boolean;
  readonly active: boolean;
  readonly activeFormVersionId?: Uuid | null;
  /** Extra admin fields. The backend fills them only for an authorized reader. */
  readonly key?: string | null;
  readonly gremiumId?: Uuid | null;
}

/** `TransitionOut`. The `label` is an i18n map. */
export interface TransitionOutWire {
  readonly id: Uuid;
  readonly fromStateId: Uuid;
  readonly toStateId: Uuid;
  readonly label: I18nMap;
  /** Optional color for the decision button. */
  readonly color?: string | null;
  /** The transition carries an `addToNextSession` action into a vote state, so a
   *  fire takes a `meetingId`. */
  readonly addsToAgenda?: boolean;
  /** The gremium whose planned meetings the agenda dialog offers. */
  readonly agendaGremiumId?: Uuid | null;
  /** The target is an accepted state of the cost center, so a fire takes a decision. */
  readonly allowsDecision?: boolean;
}

/** A field change in the version diff (`FieldChange`). */
export interface FieldChangeWire {
  readonly old: unknown;
  readonly new: unknown;
}

/**
 * Structural diff of two `data` snapshots (`DataDiff`). `added` and `removed` are
 * field-value maps. `changed` maps a key to `{old,new}`.
 *
 * The backend compares a nested field as one whole value. It runs no recursive
 * cell diff. That also works for heterogeneous tables and objects.
 */
export interface DataDiffWire {
  readonly added: Readonly<Record<string, unknown>>;
  readonly removed: Readonly<Record<string, unknown>>;
  readonly changed: Readonly<Record<string, FieldChangeWire>>;
}

/**
 * `VersionOut`. One submission version and its diff.
 *
 * The applicant view gets the metadata only: `data` and `diff` are null, and
 * `changedKeys` lists the changed fields. A reader without the PII right gets no
 * `isPII` field in `data`, `diff` and `changedKeys`.
 */
export interface VersionOutWire {
  readonly version: number;
  readonly data?: Readonly<Record<string, unknown>> | null;
  readonly diff?: DataDiffWire | null;
  readonly changedKeys?: readonly string[];
  readonly changedBy?: string | null;
  /** The resolved editor. The UI renders this and never the raw `changedBy`. */
  readonly changedByInfo?: ActorInfo | null;
  readonly at: IsoDateTime;
}

/**
 * `AttachmentOut`. Attachment metadata.
 *
 * `scanned` means that the ClamAV run finished. It does not mean "clean". The API
 * hides the scan result (`scan_result`) on purpose. If the scan finds something,
 * the backend deletes the object. Clean and infected only separate at download
 * time: 200 against 409.
 */
export interface AttachmentOutWire {
  readonly id: Uuid;
  readonly filename: string;
  readonly mime: string;
  readonly size: number;
  readonly scanned: boolean;
}

/**
 * `DraftAttachmentOut` (files/schemas.py): 201 of `POST /apply/attachments`. The
 * attachment fields stay snake_case like `AttachmentOut`; the token fields are camelCase.
 */
export interface DraftAttachmentOutWire extends AttachmentOutWire {
  readonly draftToken: string;
  readonly draftExpiresAt: IsoDateTime;
}

/**
 * `SignedUrlOut` (files/schemas.py). An app-relative /download route behind an
 * authorization check. `expiresIn` is an advisory cache hint for the frontend. It
 * is not a URL expiry.
 */
export interface SignedUrlOutWire {
  readonly url: string;
  readonly expiresIn: number;
}

/** Body for `POST /applications` (`ApplicationCreate`, by_alias). */
export interface ApplicationCreateBody {
  readonly typeId: Uuid;
  readonly data: Readonly<Record<string, unknown>>;
  /**
   * Optional. For a logged-in user the backend takes the identity from the account. For an
   * anonymous submission the server requires this field and `applicantName`.
   */
  readonly applicantEmail?: string | null;
  readonly applicantName?: string | null;
  readonly lang: Lang;
  readonly altcha?: string | null;
  /** Draft uploads of the wizard to bind. Needs `draftToken`. */
  readonly attachmentIds?: readonly Uuid[];
  /** The token of the draft uploads. */
  readonly draftToken?: string | null;
  /** The Vorgänger of a Folgeantrag; needs a login and the read right. */
  readonly predecessorId?: Uuid | null;
}

/** Body for `POST /applications/{id}/comments` (`CommentCreate`). */
export interface CommentCreateBody extends MessageFiles {
  readonly body: string;
  readonly visibility: CommentVisibility;
  /** The ids of the people the text mentions; only a member sends them. */
  readonly mentions?: readonly Uuid[];
}

/** Body for `POST /applications/{id}/transition` (`TransitionRequest`). */
export interface TransitionRequestBody {
  readonly transitionId: Uuid;
  readonly note?: string | null;
  /**
   * The meeting whose agenda gets the application. Only for a transition with
   * `addsToAgenda`; the meeting must be planned and belong to `agendaGremiumId`, else
   * the server answers 422 `agenda_meeting_invalid`.
   */
  readonly meetingId?: Uuid | null;
  /** The new agenda item is not public (NÖ). Only with `meetingId`. */
  readonly nonPublic?: boolean;
  /** The decision. Only for a transition with `allowsDecision`, else 422. */
  readonly decision?: DecisionProposal | null;
}

/** `POST /applications/{id}/force-status`. A privileged direct status override.
 *  `note` holds the reason and is mandatory. The change skips the flow. The audit
 *  log records it. */
export interface ForceStatusBody {
  readonly stateId: Uuid;
  readonly note: string;
}

/** `TransitionResult`. The 200 response of a transition that succeeded. */
export interface TransitionResult {
  readonly newStateId: Uuid;
  readonly statusEventId: Uuid;
  readonly dispatchedActions: readonly string[];
}

/** Application status with the label resolved for the current `lang`. */
export interface ApplicationState {
  readonly id: Uuid;
  readonly key: string;
  readonly label: string;
  /** Optional display color of the state badge, as hex. */
  readonly color?: string | null;
  readonly editAllowed: boolean;
  /** State kind: normal|vote. */
  readonly kind: string;
}

export interface Applicant {
  readonly email: string | null;
  readonly name: string | null;
  readonly anonymized: boolean;
}

export interface Application {
  readonly id: Uuid;
  readonly typeId: Uuid;
  readonly state: ApplicationState | null;
  readonly gremiumId: Uuid | null;
  /** The gremium that decides the current vote (snapshot on entry of a vote state). */
  readonly voteGremiumId?: Uuid | null;
  readonly budgetId: Uuid | null;
  readonly fiscalYearId: Uuid | null;
  readonly amount: string | null;
  readonly currency: string | null;
  readonly data: Readonly<Record<string, unknown>>;
  readonly version: number;
  readonly lang: string | null;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
  readonly applicant: Applicant | null;
  /** True if the requester may edit or delete. A manager, a holder of
   *  `application.edit_any` or the creator may. */
  readonly canEdit: boolean;
  /** True if the requester holds `application.edit_any`: a state with `editAllowed`
   *  false does not lock the edit for this requester. */
  readonly canEditLocked: boolean;
  /** True if the requester is the creator, that is the applicant. It gates the
   *  anonymization request under GDPR Art. 17. Only the data subject may ask. */
  readonly isOwner: boolean;
  /**
   * When it was archived, or null. A timestamp rather than a flag, so the view can say
   * WHEN without a second field.
   *
   * Archiving is not anonymisation: the record is complete and readable, it has only
   * left the working list. `be-privacy` owns the DSGVO erasure people confuse this with.
   */
  readonly archivedAt: IsoDateTime | null;
  /** Time of the last status change, for "since" on the status page. */
  readonly stateSince?: IsoDateTime | null;
  /**
   * The `isPII` field keys that the server removed from `data`. The edit form
   * leaves out these fields. A key that is only missing from `data` was never
   * answered, and the field stays editable.
   */
  readonly hiddenKeys?: readonly string[];
  /** Set when a person captured the application on behalf of the applicant. */
  readonly capture?: ApplicationCapture | null;
  /** The amount that the cost center binds. `null` means as requested. */
  readonly approvedAmount?: string | null;
  /** The valid decision, or `null` before one. */
  readonly decision?: ApplicationDecision | null;
}

export interface ApplicationListItem {
  readonly id: Uuid;
  readonly typeId: Uuid;
  readonly title: string | null;
  readonly state: ApplicationState | null;
  readonly gremiumId: Uuid | null;
  readonly amount: string | null;
  /** The approved amount. `null` means as requested. */
  readonly approvedAmount?: string | null;
  readonly currency: string | null;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
  /** Set when the row is archived, so a combined list can mark it. */
  readonly archivedAt: IsoDateTime | null;
  /** Time of the last status change, for "waiting since". */
  readonly stateSince?: IsoDateTime | null;
}

/** A Vorgänger or a Folgeantrag, frontend view. */
export interface LinkedApplication {
  readonly id: Uuid;
  readonly title: string | null;
  readonly state: ApplicationState | null;
  readonly createdAt: IsoDateTime;
  readonly archived: boolean;
}

/** One change of the Vorgänger link, frontend view. A hidden Vorgänger is null. */
export interface ApplicationLinkEvent {
  readonly action: 'set' | 'removed';
  readonly at: IsoDateTime;
  readonly actorInfo: ActorInfo | null;
  readonly predecessor: LinkedApplication | null;
}

/** The links of one application, frontend view. */
export interface ApplicationLinks {
  readonly predecessor: LinkedApplication | null;
  readonly successors: readonly LinkedApplication[];
  readonly events: readonly ApplicationLinkEvent[];
}

/** Result of `POST /applications`, frontend view. */
export interface ApplicationCreated {
  readonly applicationId: Uuid;
}

/** Timeline entry, frontend view. The `label` comes from `toState`. */
export interface TimelineEntry {
  readonly toStateId: Uuid;
  readonly toState: ApplicationState | null;
  readonly label: string;
  /** Label of the fired transition, resolved to the locale. */
  readonly transitionLabel?: string | null;
  readonly actor: string | null;
  readonly actorInfo?: ActorInfo | null;
  readonly at: IsoDateTime;
  readonly note: string | null;
  /** The vote whose close fired the event, for the link to it. */
  readonly voteId: Uuid | null;
  /** The vote that fired the event was deleted with its meeting. */
  readonly voteDeleted: boolean;
  /** The decision that this status change carried. */
  readonly decision?: TimelineDecision | null;
}

/** Comment, frontend view. `isPublic` comes from `visibility`. */
export interface ApplicationComment {
  readonly id: Uuid;
  readonly author: string | null;
  readonly authorKind: CommentAuthorKind;
  readonly authorInfo?: ActorInfo | null;
  readonly body: string;
  readonly visibility: CommentVisibility;
  readonly isPublic: boolean;
  /** True if the viewer wrote this comment. Own messages go right, others left and gray. */
  readonly isOwn: boolean;
  readonly at: IsoDateTime;
  /** When the text was last changed: the chat says "bearbeitet". */
  readonly editedAt?: IsoDateTime | null;
  /** The files of the comment, oldest first. */
  readonly attachments: readonly MessageAttachment[];
  /** The people the comment mentions. */
  readonly mentions: readonly PersonRef[];
}

/** Application type, frontend view, for the wizard selection. */
export interface ApplicationType {
  readonly id: Uuid;
  readonly name: string;
  readonly active: boolean;
  readonly hasBudget: boolean;
  readonly activeFormVersionId: Uuid | null;
  readonly key: string | null;
  readonly gremiumId: Uuid | null;
}

/** Available transition, frontend view, with the `label` resolved. */
export interface Transition {
  readonly id: Uuid;
  readonly fromStateId: Uuid;
  readonly toStateId: Uuid;
  readonly label: string;
  /** Optional color for the decision button. `null` selects the default. */
  readonly color: string | null;
  /**
   * The transition puts the application on the agenda of a meeting and leads into a
   * vote state, so the server takes a chosen meeting. The detail and the row menu
   * open the agenda dialog for it, which asks for the meeting. A transition whose
   * action leads into a normal state is `false` here and fires as a plain transition;
   * the server action then picks the next planned meeting.
   */
  readonly addsToAgenda: boolean;
  /** The gremium whose planned meetings the agenda dialog offers, or null. */
  readonly agendaGremiumId: Uuid | null;
  /**
   * The target is an accepted state of the cost center. The detail and the row
   * menu then open the decision dialog, which can approve with deviations.
   */
  readonly allowsDecision?: boolean;
}

/** A changed field cell, frontend view. The `key` comes out of the diff map. */
export interface FieldChange {
  readonly key: string;
  readonly old: unknown;
  readonly new: unknown;
}

/**
 * Version diff, frontend view. The backend sends the maps `added`, `removed` and
 * `changed`. This shape turns them into lists that carry the key. A template can
 * then render them directly with `@for`.
 *
 * The lists stay mutable arrays, because `ConfigDiffData` of the ui-kit, which the diff view
 * takes as input, declares mutable arrays.
 */
export interface DataDiff {
  readonly added: { readonly key: string; readonly value: unknown }[];
  readonly removed: { readonly key: string; readonly value: unknown }[];
  readonly changed: FieldChange[];
}

/** A submission version, frontend view, for the history and diff view. */
export interface ApplicationVersion {
  readonly version: number;
  readonly data: Readonly<Record<string, unknown>>;
  readonly diff: DataDiff | null;
  /** Keys of the changed fields. The applicant view gets only these. */
  readonly changedKeys?: readonly string[];
  readonly changedBy: string | null;
  readonly changedByInfo?: ActorInfo | null;
  readonly at: IsoDateTime;
}

/**
 * Scan state of an attachment, frontend view. The contract gives it:
 * - `scanning`: `scanned=false`. ClamAV still runs. A download returns 409.
 * - `clean`: `scanned=true`. The scan finished. A download normally works.
 * - `quarantined`: the client sets this when a download fails with 409, that is
 *   on a finding or a quarantine. The metadata alone does not show this state.
 */
export type ScanState = 'scanning' | 'clean' | 'quarantined';

/**
 * The file of a chat message (ticket note, card comment, application comment). The
 * server sets `scanState`: only a `clean` file downloads, streamed through the API.
 */
export interface MessageAttachment {
  readonly id: Uuid;
  readonly filename: string;
  readonly mime: string;
  readonly size: number;
  readonly scanState: ScanState;
}

/** The files of a message create: draft ids of `POST /apply/attachments` and their token. */
export interface MessageFiles {
  /** At most 5. */
  readonly attachmentIds?: readonly Uuid[];
  /** Required with `attachmentIds`. */
  readonly draftToken?: string | null;
}

/** Attachment, frontend view. `scanState` is derived. */
export interface Attachment {
  readonly id: Uuid;
  readonly filename: string;
  readonly mime: string;
  readonly size: number;
  readonly scanned: boolean;
  readonly scanState: ScanState;
}

/** Signed download URL, frontend view. */
export interface SignedUrl {
  readonly url: string;
  readonly expiresIn: number;
}

/** Frontend input for a new application. It maps to `ApplicationCreateBody`. */
export interface NewApplication {
  readonly typeId: Uuid;
  readonly data: Readonly<Record<string, unknown>>;
  /**
   * Null for a logged-in user, like `applicantName`. The backend takes the identity and the
   * altcha itself.
   */
  readonly applicantEmail?: string | null;
  readonly applicantName?: string | null;
  readonly lang: Lang;
  readonly altcha?: string | null;
  /** Draft uploads of the wizard to bind. */
  readonly attachmentIds?: readonly Uuid[];
  /** The token of the draft uploads; required with `attachmentIds`. */
  readonly draftToken?: string | null;
  /** The Vorgänger of a Folgeantrag; needs a login and the read right. */
  readonly predecessorId?: Uuid | null;
}

/**
 * A draft upload of the wizard, frontend view: the attachment plus the field it
 * belongs to (`null` = the general block "Anhänge").
 */
export interface DraftAttachment extends Attachment {
  readonly fieldKey: string | null;
}

/** The result of `POST /apply/attachments`: the draft and its (new) token. */
export interface DraftUpload {
  readonly attachment: Attachment;
  readonly draftToken: string;
  readonly draftExpiresAt: IsoDateTime;
}

/**
 * The type of a form field, a mirror of the backend `FormFieldDef`.
 *
 * - `gremium_select` and `budget_select` are dynamic pickers. The server injects the
 *   options: Gremien or the budget tree.
 * - `email` and `iban` are typed inputs with built-in validation.
 * - `daterange` is a date range `{from, to}`.
 * - `funding` is the requested funding, separate from the cost total of the positions.
 */
export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'currency'
  | 'date'
  | 'select'
  | 'multiselect'
  | 'gremium_select'
  | 'budget_select'
  | 'email'
  | 'iban'
  | 'daterange'
  | 'checkbox'
  | 'file'
  | 'table'
  | 'markdown'
  | 'computed'
  | 'positions'
  | 'funding'
  | 'section';

/**
 * One option of a select field. The server sets `parentId`, `key` and `color` on the
 * options of `budget_select`, so the form shows the cost centres as a tree.
 */
export interface FieldOption {
  readonly value: string;
  readonly label: I18nMap;
  /** The value of the parent cost centre, or null for a top-level one. */
  readonly parentId?: string | null;
  /** The path segment of the cost centre. */
  readonly key?: string | null;
  /** The own display colour of the cost centre, or null. */
  readonly color?: string | null;
}

export interface FieldValidation {
  readonly min?: number;
  readonly max?: number;
  readonly minLen?: number;
  readonly maxLen?: number;
  readonly pattern?: string;
  readonly fileTypes?: readonly string[];
  readonly maxSizeMB?: number;
  readonly maxRows?: number;
  /** `positions`. The minimum comparison offers per position and the minimum
   *  number of positions. */
  readonly minOffers?: number;
  readonly minPositions?: number;
  /** `positions`. Allow the opt-out of comparison offers for one position. The
   *  user ticks a checkbox and must give a reason. Then one offer is enough. If
   *  unset, the opt-out is allowed. */
  readonly allowNoOffers?: boolean;
}

/** A field definition of the effective form. It is camelCase like the OpenAPI by_alias. */
export interface FormFieldDef {
  readonly key: string;
  readonly type: FieldType;
  readonly label: I18nMap;
  readonly help?: I18nMap;
  readonly required?: boolean;
  readonly validation?: FieldValidation;
  readonly options?: readonly FieldOption[];
  readonly visibleIf?: Readonly<Record<string, unknown>>;
  readonly compute?: Readonly<Record<string, unknown>>;
  readonly isPII?: boolean;
  readonly isPromoted?: boolean;
  readonly promoteTarget?: string;
}

export interface FormSection {
  readonly key: string;
  readonly label: I18nMap;
  readonly fields: readonly FormFieldDef[];
}

/** Effective form definition. GET /api/application-types/{id}/form. */
export interface EffectiveForm {
  readonly applicationTypeId: Uuid;
  readonly formVersionId: Uuid;
  /** Drives `visibleIf: has_budget`. Comes from the type, as the server's own check does. */
  readonly hasBudget: boolean;
  readonly sections: readonly FormSection[];
}

/**
 * Response of POST /api/auth/magic-link/verify (`MagicLinkVerifyOut`). It is a
 * plain `BaseModel` and not a `_CamelModel`, so the field names stay snake_case,
 * for example `application_id`. The applicant session runs only through an
 * HttpOnly cookie. The body carries no session token. JavaScript never sees one.
 */
export interface MagicLinkVerifyResult {
  readonly application_id: Uuid;
  /** Always `edit`: the applicant session has no scope. */
  readonly scope: 'edit';
}

/** Body of POST /api/auth/email-login: the address and the ALTCHA solution. */
export interface EmailLoginRequest {
  readonly email: string;
  readonly altcha: string | null;
}

/** One Antrag of the address of an e-mail session (GET /api/applicant/applications). */
export interface ApplicantApplicationItem {
  readonly id: Uuid;
  readonly title: string | null;
  readonly state: StateOutWire | null;
  readonly typeId: Uuid;
  readonly amount: string | null;
  readonly approvedAmount: string | null;
  readonly currency: string | null;
  readonly createdAt: IsoDateTime;
}

/** The Anträge of the e-mail session, newest first, and the address of the session. */
export interface ApplicantApplications {
  readonly email: string | null;
  readonly items: readonly ApplicantApplicationItem[];
}

export type MajorityRule = 'simple' | 'absolute' | 'two_thirds';
/** `draft`: planned, not open yet. `cancelled`: the application left the vote state by hand, so the vote stopped. */
export type VoteStatus = 'draft' | 'open' | 'closed' | 'cancelled';
/** A motion gives `passed`, `rejected` or `tie`. A personnel election gives
 *  `elected`, `runoff` (a runoff decides the open seats), `tie` (the lot decides) or
 *  `rejected` (quorum missed, or nobody elected). */
export type VoteResult = 'passed' | 'rejected' | 'tie' | 'elected' | 'runoff';
/** `motion`: a decision (Ja/Nein/Enthaltung). `election`: a personnel election.
 *  `poll`: a poll ("Umfrage") that only counts the answers. */
export type VoteKind = 'motion' | 'election' | 'poll';

/** `single`: one option or an abstention. `multi`: 0 to `maxChoices` options.
 *  `date`: Ja/Vielleicht/Nein for every date. */
export type PollMode = 'single' | 'multi' | 'date';
/** The answer of a date poll for one date. */
export type DateAnswer = 'yes' | 'maybe' | 'no';

/** One option of a poll: a text (`label`), or a date with a start and an optional end.
 *  The server gives the ids (`o1`..`on`). */
export interface PollOption {
  readonly id: string;
  readonly label?: string | null;
  readonly start?: IsoDateTime | null;
  readonly end?: IsoDateTime | null;
}

/** The config of a poll (`PollConfig`). */
export interface PollConfig {
  readonly mode: PollMode;
  readonly options: readonly PollOption[];
  /** A multi poll: the most options of one ballot. `null` = every option. */
  readonly maxChoices?: number | null;
  readonly secret: boolean;
  readonly guestsVote?: boolean;
}

/** The counts of a poll (`PollResultOut`): stored at the close, live once revealed. */
export interface PollResult {
  /** Votes per option id. A date poll counts the Ja answers here. */
  readonly counts: Readonly<Record<string, number>>;
  /** A date poll: the Vielleicht answers per option id. */
  readonly maybe?: Readonly<Record<string, number>> | null;
  readonly abstentions: number;
  readonly ballots: number;
  /** The option ids, highest first. */
  readonly order: readonly string[];
  /** The options with the most votes (every tied one); empty without a vote. */
  readonly top: readonly string[];
}

/** The body of a new poll (`PollIn`): the options as the creator types them. */
export interface PollIn {
  readonly mode: PollMode;
  readonly options: readonly {
    readonly label?: string;
    readonly start?: IsoDateTime;
    readonly end?: IsoDateTime;
  }[];
  readonly maxChoices?: number | null;
}

/** `POST /votes`: a poll of a Gremium, without a meeting. */
export interface PollCreateBody extends PollIn {
  readonly kind: 'poll';
  readonly eligibleGroup: Uuid;
  readonly question: string;
  readonly secret: boolean;
  /** The planned end, at least one hour ahead. */
  readonly closesAt: IsoDateTime;
  /** Keep the poll a draft; otherwise it opens at once. */
  readonly draft: boolean;
}

/** One candidate of a personnel election. The server gives the ids (`c1`..`cn`). */
export interface ElectionCandidate {
  readonly id: string;
  readonly name: string;
  /** The account of the candidate, or `null` for a free name. */
  readonly principalId?: Uuid | null;
  /** The DSGVO erasure removed the name (`name` then holds the German placeholder
   *  "Gelöscht"): the UI shows `election.candidate.erased` instead. Only the server
   *  sets it. */
  readonly erased?: boolean;
}

/**
 * The config of a personnel election (`ElectionConfig`). Each voter gives up to
 * `seats` votes, at most one per candidate. One candidate for one seat gives a
 * Ja/Nein/Enthaltung ballot.
 */
export interface ElectionConfig {
  readonly seats: number;
  readonly candidates: readonly ElectionCandidate[];
  readonly secret: boolean;
  readonly quorum?: Quorum | null;
  readonly abstainCountsQuorum?: boolean;
  readonly guestsVote?: boolean;
}

/** The runoff that a tie at the seat boundary needs. `voteId` is set once it exists. */
export interface ElectionRunoff {
  readonly candidateIds: readonly string[];
  readonly seats: number;
  readonly voteId?: Uuid | null;
}

/** The lot of a tie. `drawn` is `null` while the lot is pending. */
export interface ElectionLot {
  readonly among: readonly string[];
  readonly seats: number;
  readonly drawn: readonly string[] | null;
  readonly at?: IsoDateTime | null;
  readonly by?: string | null;
  readonly byName?: string | null;
}

/** The stored result of a closed election (`ElectionResultOut`). */
export interface ElectionResult {
  /** Votes per candidate id (`yes`/`no` for a single candidate). */
  readonly counts: Readonly<Record<string, number>>;
  readonly abstentions: number;
  readonly ballots: number;
  readonly yes?: number | null;
  readonly no?: number | null;
  /** The elected candidate ids, best first. */
  readonly elected: readonly string[];
  readonly runoff?: ElectionRunoff | null;
  readonly lot?: ElectionLot | null;
}

/** The election fields of a vote and the poll fields. A motion has
 *  `kind: 'motion'` and no others. */
export interface ElectionFields {
  readonly kind?: VoteKind;
  readonly election?: ElectionConfig | null;
  readonly electionResult?: ElectionResult | null;
  /** The election that this runoff continues. */
  readonly parentVoteId?: Uuid | null;
  /** 1 for the first round, 2 for the first runoff. */
  readonly round?: number;
  /** A poll: its mode and options. */
  readonly poll?: PollConfig | null;
  /** A poll: the counts once closed, or while open once revealed. */
  readonly pollResult?: PollResult | null;
}

/** Quorum threshold. */
export interface Quorum {
  readonly type: 'count' | 'percent';
  readonly value: number;
}

/**
 * Vote configuration (`VoteConfig`). The backend `_CamelModel` sends the fields in
 * camelCase. The defaults mirror the Pydantic defaults: `abstainCountsQuorum` is
 * true, `secret` is false. The frontend never sets a tie break: a tie is a
 * rejection.
 */
export interface VoteConfig {
  readonly options: readonly string[];
  readonly majorityRule: MajorityRule;
  readonly quorum?: Quorum | null;
  readonly abstainCountsQuorum?: boolean;
  readonly secret?: boolean;
  /** Admitted guests of a public meeting vote too: no quorum, majority of the cast votes. */
  readonly guestsVote?: boolean;
}

/**
 * The own ballot of the caller in one vote (`MyBallot`). `choice` is the chosen
 * option. A secret vote keeps the choice apart from the identity, so there `choice`
 * is always `null` and only `cast` tells that the caller voted.
 */
export interface MyBallot {
  readonly cast: boolean;
  readonly choice: string | null;
  /** The chosen candidate ids of an open election ballot, or the chosen option
   *  ids of an open single or multi poll. */
  readonly choices?: readonly string[] | null;
  /** The answers of an open date poll ballot. */
  readonly answers?: Readonly<Record<string, DateAnswer>> | null;
}

/**
 * Aggregated interim or final result (`TallyOut`). For a `secret` vote the server
 * returns only `counts`. It never returns an individual voter.
 */
export interface Tally {
  readonly counts: Readonly<Record<string, number>>;
  readonly eligible: number;
  readonly quorumMet: boolean;
  readonly leading: string | null;
  readonly result?: VoteResult | null;
  /** Turnout: the ballots cast so far. The server always sends it, also while the
   *  counts stay hidden. */
  readonly voted?: number;
  /** The present members of the meeting (the reveal denominator). It is 0 for a vote
   *  without a meeting and for a closed vote. */
  readonly present?: number;
  /** `counts` and `leading` are visible: the vote is closed, or it is open, not secret
   *  and every present member voted (a vote without a meeting is always visible).
   *  Otherwise `counts` is empty. */
  readonly revealed?: boolean;
  /** Why a closed vote failed: `quorum` or `majority`. `null` while open, on a pass and
   *  on a tie. */
  readonly failedReason?: 'quorum' | 'majority' | null;
  /** The present members and the admitted guests: live while open, fixed at the close.
   *  `null` for a vote that closed before public meetings existed. */
  readonly presentMembers?: number | null;
  readonly presentGuests?: number | null;
}

/**
 * Vote state and tally. GET /api/votes/{id} (`VoteOut`). It is a plain
 * `_CamelModel`, so the frontend uses it 1:1 as a view model. It carries no i18n
 * label. The options are raw keys. The frontend translates them through
 * `vote.option.*`.
 */
export interface Vote extends ElectionFields {
  readonly id: Uuid;
  /** `null` marks a motion on a free-text agenda item, with no application. */
  readonly applicationId: Uuid | null;
  /** The meeting that holds the vote. `null` marks a standalone (async) vote.
   *  A meeting-bound vote is deleted through its meeting, never through
   *  `DELETE /votes/{id}` (that route answers 409). */
  readonly meetingId?: Uuid | null;
  /** The agenda item of a meeting vote. The page reads its number ("TOP 3") from the
   *  agenda. */
  readonly agendaItemId?: Uuid | null;
  /** The motion of a meeting vote. A standalone vote often has none. */
  readonly question?: string | null;
  readonly eligibleGroup: string;
  readonly config: VoteConfig;
  readonly status: VoteStatus;
  readonly opensAt: IsoDateTime | null;
  /** The planned end of the cast window (a deadline), not the real end. */
  readonly closesAt: IsoDateTime | null;
  readonly result: VoteResult | null;
  readonly secret: boolean;
  /** Copies of `config.majorityRule` and `config.quorum` for the vote card. */
  readonly majorityRule?: MajorityRule;
  readonly quorum?: Quorum | null;
  /** The real moment when the vote opened. */
  readonly openedAt?: IsoDateTime | null;
  /** The real moment when the vote ended (close or cancel). `null` while it runs. */
  readonly closedAt?: IsoDateTime | null;
  readonly tally: Tally;
  /** The own ballot of the caller. Only `GET /votes/{id}` sets it. */
  readonly myBallot?: MyBallot | null;
  /** Admitted guests vote too: no quorum, the majority of the cast votes decides. */
  readonly guestsVote?: boolean;
  /** The caller cast the ballot of a delegator in this vote. Only `GET /votes/{id}`
   *  sets it. */
  readonly representedCast?: boolean;
  /** The caller may open, close, cancel and delete the vote: the admin role, or the
   *  gremium permission `vote.manage` or `session.manage` in the gremium of the vote.
   *  Only `GET /votes/{id}` sets it. */
  readonly canManage?: boolean;
  /** The caller may cast an own ballot: the gremium permission `vote.cast` in the
   *  gremium of the vote, in a browser session. A delegated ballot has its own check.
   *  Only `GET /votes/{id}` sets it. */
  readonly canCast?: boolean;
}

/**
 * One row of the vote list (`GET /votes`, `VoteListItem`). The row carries no tally;
 * `GET /votes/{id}` reads it. `myBallot` and `canCast` are the own ballot state of the
 * caller: a secret vote gives only `cast`, never the choice. `meetingTitle` and
 * `agendaPosition` (the number of the agenda item, "TOP 3") are `null` for a vote
 * without a meeting. `gremiumName` is `null` when the vote names no gremium.
 */
export interface VoteListItem {
  readonly id: Uuid;
  readonly question: string | null;
  readonly status: VoteStatus;
  readonly result: VoteResult | null;
  readonly secret: boolean;
  readonly kind?: VoteKind;
  readonly applicationId: Uuid | null;
  readonly meetingId: Uuid | null;
  readonly meetingTitle: string | null;
  readonly agendaItemId: Uuid | null;
  readonly agendaPosition: number | null;
  readonly gremiumId: Uuid | null;
  readonly gremiumName: string | null;
  readonly createdAt: IsoDateTime;
  readonly openedAt: IsoDateTime | null;
  readonly closedAt: IsoDateTime | null;
  /** The planned end of the cast window, not the real end. */
  readonly closesAt: IsoDateTime | null;
  readonly canCast: boolean;
  readonly myBallot: MyBallot;
}

/**
 * The filters of `GET /votes`. `status` repeats; without it the server leaves out the
 * drafts. `q` searches the question and the meeting title.
 */
export interface VoteListQuery {
  readonly status?: readonly VoteStatus[];
  readonly gremiumId?: Uuid;
  readonly q?: string;
  /** Only the motions, the elections or the polls. */
  readonly kind?: VoteKind;
  readonly limit?: number;
  readonly offset?: number;
}

/** A ballot: one option, the chosen ids of an election or a poll (`[]` = abstention),
 *  or the answer per date of a date poll. */
export type BallotChoice = string | readonly string[] | Readonly<Record<string, DateAnswer>>;

/** Response to an accepted ballot. POST /api/votes/{id}/ballot. A ballot never
 *  changes after the cast: a second cast gives 409 `already_voted`. */
export interface BallotResult {
  readonly status: 'cast';
}

/**
 * Result of `POST /votes/{id}/close` (`VoteClosed`). The close always ends the vote.
 * `branchFired` is false when the pass or fail transition of the application did not
 * fire (the guard failed, or the state has no such transition). A person must then
 * move the application by hand.
 */
export interface VoteClosed {
  readonly id: Uuid;
  readonly meetingId?: Uuid | null;
  readonly applicationId?: Uuid | null;
  /** `null` for a poll: a poll only counts. */
  readonly result: VoteResult | null;
  readonly tally: Tally;
  readonly kind?: VoteKind;
  readonly electionResult?: ElectionResult | null;
  readonly pollResult?: PollResult | null;
  readonly closedAt?: IsoDateTime | null;
  readonly firedTransitionId?: Uuid | null;
  readonly newStateId?: Uuid | null;
  readonly branchFired: boolean;
}

/** Meeting status. The backend enum is `planned|live|closed`. */
export type MeetingStatus = 'planned' | 'live' | 'closed';
/** `draft`: planned, not open yet. `cancelled`: the application left the vote state by hand, so the vote stopped. */
export type MeetingVoteStatus = 'draft' | 'open' | 'closed' | 'cancelled';

/** `MeetingVoteOut`. A vote summary in the meeting state. GET /meetings/{id}. */
export interface MeetingVoteOutWire extends ElectionFields {
  readonly id: Uuid;
  /** `null` marks a generic motion on a free-text agenda item, with no application. */
  readonly applicationId?: Uuid | null;
  /** The agenda item the vote belongs to. The frontend groups by it. */
  readonly agendaItemId?: Uuid | null;
  /** Application title. The backend supplies it. Otherwise read it from the application. */
  readonly title?: string | null;
  /** Motion of the live vote. The protocol needs it. */
  readonly question?: string | null;
  /** Options a voter can pick. */
  readonly options?: readonly string[] | null;
  readonly status: MeetingVoteStatus;
  /** Final result, for example `accepted` or `rejected`. Set only after `closed`. */
  readonly result?: string | null;
  readonly counts?: Readonly<Record<string, number>> | null;
  readonly leading?: string | null;
  readonly closesAt?: IsoDateTime | null;
  readonly voted?: number | null;
  readonly present?: number | null;
  readonly revealed?: boolean | null;
  /** Reason for the rejection. `quorum` means the vote missed the quorum.
   *  `majority` means the vote missed the majority. */
  readonly failedReason?: 'quorum' | 'majority' | null;
  readonly majorityRule?: MajorityRule;
  readonly secret?: boolean;
  readonly quorum?: Quorum | null;
  /** The real open time and the real end time (close or cancel). */
  readonly openedAt?: IsoDateTime | null;
  readonly closedAt?: IsoDateTime | null;
  /** The own ballot of the caller. A secret vote gives only `cast`. */
  readonly myBallot?: MyBallot | null;
  /** The caller cast the ballot of a delegator in this vote. */
  readonly representedCast?: boolean;
  /** Admitted guests vote too (public meeting): no quorum. */
  readonly guestsVote?: boolean;
  /** Present members and admitted guests (live while open, fixed at the close). */
  readonly presentMembers?: number | null;
  readonly presentGuests?: number | null;
  /** The decision proposal of an application vote. */
  readonly proposal?: DecisionProposal | null;
  /** A repeat ("Erneut abstimmen"): the closed vote of the same agenda item it repeats. */
  readonly repeatOfId?: Uuid | null;
  /** The number of the vote in its repeat chain: 1 for a first vote, 2 for the first repeat. */
  readonly attempt?: number;
}

/** `MeetingOut`. Meeting state and votes. GET /meetings/{id}. */
/**
 * `KeeperPeriodOut`. One period of a protocol keeper. `fromAt` is `null`
 * for the planned handover, `toAt` is `null` while the period runs. The positions
 * are 1-based numbers in the current agenda order, `null` without an item.
 */
export interface KeeperPeriod {
  readonly principalId: Uuid;
  readonly name: string | null;
  readonly fromAt: IsoDateTime | null;
  readonly toAt: IsoDateTime | null;
  readonly fromAgendaItemId: Uuid | null;
  readonly toAgendaItemId: Uuid | null;
  readonly fromPosition: number | null;
  readonly toPosition: number | null;
}

/** How the minutes change hands: at once, or with the next agenda item. */
export type HandoverMode = 'now' | 'next_item';

export interface MeetingOutWire {
  readonly id: Uuid;
  readonly title: string;
  readonly date?: string | null;
  readonly startTime?: string | null;
  readonly endTime?: string | null;
  readonly status: MeetingStatus;
  readonly activeApplicationId?: Uuid | null;
  /** The agenda item the room handles now. */
  readonly currentAgendaItemId?: Uuid | null;
  /** Number (1-based, in agenda order) and title of the current agenda item. */
  readonly currentAgendaItem?: CurrentAgendaItem | null;
  /** Number of items on the agenda. */
  readonly agendaItemCount?: number;
  /** The real start. `null` before the start and for an older meeting. */
  readonly startedAt?: IsoDateTime | null;
  /** The close sets it. */
  readonly closedAt?: IsoDateTime | null;
  readonly gremiumId?: Uuid | null;
  readonly gremiumName?: string | null;
  readonly votes: readonly MeetingVoteOutWire[];
  /** The linked protocol, if it already exists. */
  readonly protocolId?: Uuid | null;
  readonly createdAt: IsoDateTime;
  readonly protokollantId?: Uuid | null;
  readonly protokollantName?: string | null;
  /** True if the requesting user is the assigned protokollant. The server resolves it. */
  readonly isProtokollant?: boolean;
  /** Master flag. True if the user may run the meeting: protocol, agenda, status. */
  readonly canControl?: boolean;
  /** Manage the meeting: create it, plan it and assign the protokollant. */
  readonly canManage?: boolean;
  /** Write the protocol and the agenda. The assigned protokollant or a manager may. */
  readonly canWrite?: boolean;
  /** Open and close motions. */
  readonly canManageVotes?: boolean;
  /** Eligible to vote in this meeting. The user needs a role with `vote.cast`. */
  readonly canVote?: boolean;
  /** Finalize and send the protocol: write access plus the gremium permission
   *  `protocol.finalize`. */
  readonly canFinalize?: boolean;
  /** Delete the meeting: `canManage`, and `meeting.delete_finalized` for a final protocol. */
  readonly canDelete?: boolean;
  /** The periods of the protocol keepers, running and ended, in time order. */
  readonly keeperPeriods?: readonly KeeperPeriod[];
  /** The handover planned for the next agenda item. */
  readonly plannedHandover?: KeeperPeriod | null;
  /** Public participation over a QR code is on. */
  readonly publicJoin?: boolean;
  /** Admitted guests vote (`vote`) or only follow the meeting (`watch`). */
  readonly guestsMode?: GuestsMode;
  /** The join code (`7KQ4MP`); the server sends it to the meeting lead only. */
  readonly joinCode?: string | null;
  /** The guests admitted now. */
  readonly admittedGuests?: number;
  /** The open join requests; the meeting lead only, else 0. */
  readonly pendingGuests?: number;
  /** Public participation is possible: only a gremium without a quorum allows it. */
  readonly publicJoinAllowed?: boolean;
  /** The earliest open of a planned meeting with a date (UTC), else `null`. */
  readonly opensAt?: IsoDateTime | null;
  /** Before this point the open needs `confirmEarly` (UTC), else `null`. */
  readonly confirmUntil?: IsoDateTime | null;
}

/** `ProtocolOut`. Meeting protocol. POST /meetings/{id}/protocol, PATCH /protocols/{id}. */
export interface ProtocolOutWire {
  readonly id: Uuid;
  readonly meetingId: Uuid;
  readonly markdown: string;
  /** `rendering` means finalize ran. The worker renders the PDF in the background. */
  readonly status: 'draft' | 'rendering' | 'final';
  /** Result link after `finalize`. The PDF sits in MinIO. */
  readonly pdfUrl?: string | null;
  /** Redacted public variant. It exists only if an agenda item is non-public. */
  readonly publicPdfUrl?: string | null;
  readonly sentAt?: IsoDateTime | null;
  /** The protocol is held back from the public protocol page. */
  readonly publicWithheld?: boolean;
  /** The gremium publishes its final protocols on the public protocol page. */
  readonly gremiumProtocolsPublic?: boolean;
}

/** Body for `POST /meetings` (`MeetingCreate`). */
export interface MeetingCreateBody {
  readonly title: string;
  readonly gremiumId?: Uuid | null;
  /** Planned meeting date (`YYYY-MM-DD`), optional. */
  readonly date?: string | null;
  /** Planned time (`HH:mm`), optional. */
  readonly startTime?: string | null;
  /** Planned end time (`HH:mm`), optional. It must be after `startTime`. */
  readonly endTime?: string | null;
  /** Assigned protokollant, optional. The person must be a member of the gremium. */
  readonly protokollantId?: Uuid | null;
  /** Public participation over a QR code. */
  readonly publicJoin?: boolean;
  readonly guestsMode?: GuestsMode;
}

/** Body for `PATCH /meetings/{id}`. Status, active application, date or protokollant. */
export interface MeetingPatchBody {
  readonly status?: MeetingStatus;
  readonly activeApplicationId?: Uuid | null;
  /** The agenda item the room handles now. `null` clears it. Protokollant or session lead. */
  readonly currentAgendaItemId?: Uuid | null;
  /**
   * "Nächster TOP": the item that the room leaves. The server ticks it in the same
   * request. Only together with `currentAgendaItemId`.
   */
  readonly completeAgendaItemId?: Uuid;
  /** New title (1 to 200 characters). Planned or live only: a closed meeting gives 409. */
  readonly title?: string;
  /** Planned meeting date (`YYYY-MM-DD`). Use it to schedule a planned meeting. */
  readonly date?: string | null;
  /** Planned time (`HH:mm`). */
  readonly startTime?: string | null;
  /** Planned end time (`HH:mm`). */
  readonly endTime?: string | null;
  /** (Re)assign the protokollant. */
  readonly protokollantId?: Uuid | null;
  /** Public participation on or off. Off voids the requests and ends the guests. */
  readonly publicJoin?: boolean;
  /** Guests vote or only follow. `watch` gives 409 `guest_vote_open` while a guest vote runs. */
  readonly guestsMode?: GuestsMode;
  /** Confirms an early open (`status: 'live'` before `confirmUntil`). */
  readonly confirmEarly?: boolean;
}

/** Body for `POST /protocols/{id}/votes`. It embeds votes. */
export interface ProtocolVotesBody {
  readonly voteIds: readonly Uuid[];
}

/** `CalendarFeedOut`. The own iCal subscription URL. `url` is null until a token exists. */
export interface CalendarFeed {
  readonly url: string | null;
}

/** Vote summary, frontend view. It normalizes the `null` defaults. */
export interface MeetingVote extends ElectionFields {
  readonly id: Uuid;
  /** `null` marks a generic motion on a free-text agenda item. */
  readonly applicationId: Uuid | null;
  /** The agenda item the vote belongs to. */
  readonly agendaItemId: Uuid | null;
  readonly title: string | null;
  readonly question: string | null;
  readonly options: readonly string[];
  readonly status: MeetingVoteStatus;
  readonly result: string | null;
  readonly counts: Readonly<Record<string, number>> | null;
  readonly leading: string | null;
  readonly closesAt: IsoDateTime | null;
  /** Participation progress: members who voted against members present.
   *  `revealed` tells whether `counts` and `leading` are visible. If not, the
   *  frontend shows the progress only. */
  readonly voted: number;
  readonly present: number;
  readonly revealed: boolean;
  /** Reason for the rejection. `quorum` means the vote missed the quorum.
   *  `majority` means the vote missed the majority. */
  readonly failedReason: 'quorum' | 'majority' | null;
  /** The own ballot of the caller. A secret vote gives only `cast`. `null` when the
   *  server sent none (for example a broadcast). */
  readonly myBallot?: MyBallot | null;
  /** The rules of the vote, for the vote card. A vote that a WS event added
   *  before the next GET has none of them. */
  readonly majorityRule?: MajorityRule;
  readonly secret?: boolean;
  readonly quorum?: Quorum | null;
  /** The real open time, and the real end time (close or cancel). */
  readonly openedAt?: IsoDateTime | null;
  readonly closedAt?: IsoDateTime | null;
  /** Admitted guests vote too: no quorum, majority of the cast votes. */
  readonly guestsVote?: boolean;
  /** Present members and admitted guests ("19 Mitglieder + 7 Gäste anwesend"). */
  readonly presentMembers?: number | null;
  readonly presentGuests?: number | null;
  /** The decision proposal of an application vote, for the edit of a prepared vote. */
  readonly proposal?: DecisionProposal | null;
  /** A repeat ("Erneut abstimmen"): the closed vote of the same agenda item it repeats. */
  readonly repeatOfId?: Uuid | null;
  /** The number of the vote in its repeat chain: 2 for the first repeat. */
  readonly attempt?: number;
}

/** The agenda item the room handles now, as `MeetingOut.currentAgendaItem` sends it. */
export interface CurrentAgendaItem {
  /** 1-based number in the agenda order ("TOP 3"). */
  readonly position: number;
  readonly title: string | null;
}

/** Meeting, frontend view. */
export interface Meeting {
  readonly id: Uuid;
  readonly title: string;
  /** Planned meeting date (`YYYY-MM-DD`) or `null`. */
  readonly date: string | null;
  /** Planned time (`HH:mm`) or `null`. */
  readonly startTime: string | null;
  /** Planned end time (`HH:mm`) or `null`. */
  readonly endTime: string | null;
  readonly status: MeetingStatus;
  readonly activeApplicationId: Uuid | null;
  /** The agenda item the room handles now ("Jetzt"). Followers and the beamer follow it. */
  readonly currentAgendaItemId: Uuid | null;
  /** Number (1-based, in agenda order) and title of the current agenda item. */
  readonly currentAgendaItem?: CurrentAgendaItem | null;
  /** Number of items on the agenda. */
  readonly agendaItemCount?: number;
  /** The real start. The start sets it once. `null` before the start, and for a
   *  meeting that started before the field existed: show the planned start then. */
  readonly startedAt?: IsoDateTime | null;
  /** The close sets it. */
  readonly closedAt?: IsoDateTime | null;
  readonly gremiumId: Uuid | null;
  /** Name of the gremium. The timeline shows it. */
  readonly gremiumName: string | null;
  readonly votes: readonly MeetingVote[];
  readonly protocolId: Uuid | null;
  readonly createdAt: IsoDateTime;
  readonly protokollantId: Uuid | null;
  readonly protokollantName: string | null;
  /** True if the logged-in user is the assigned protokollant of this meeting. */
  readonly isProtokollant: boolean;
  /** Master flag. True if the user may run the meeting: protocol, agenda, status. */
  readonly canControl: boolean;
  /** Manage the meeting: create it, plan it and assign the protokollant. */
  readonly canManage: boolean;
  /** Write the protocol and the agenda. The assigned protokollant or a manager may. */
  readonly canWrite: boolean;
  /** Open and close motions. */
  readonly canManageVotes: boolean;
  /** Eligible to vote in this meeting. */
  readonly canVote: boolean;
  /** Finalize and send the protocol: write access plus the gremium permission
   *  `protocol.finalize`. */
  readonly canFinalize: boolean;
  /** Delete the meeting: `canManage`, and `meeting.delete_finalized` for a final protocol.
   *  The server sets it, because the client does not know the protocol status. */
  readonly canDelete: boolean;
  /** The periods of the protocol keepers, running and ended, in time order. */
  readonly keeperPeriods: readonly KeeperPeriod[];
  /** The handover planned for the next agenda item, or `null`. */
  readonly plannedHandover: KeeperPeriod | null;
  /** Public participation over a QR code is on. */
  readonly publicJoin: boolean;
  /** Admitted guests vote or only follow the meeting. */
  readonly guestsMode: GuestsMode;
  /** The join code, for the meeting lead only (`null` for everybody else). */
  readonly joinCode: string | null;
  /** The guests admitted now. */
  readonly admittedGuests: number;
  /** The open join requests (meeting lead only, else 0). */
  readonly pendingGuests: number;
  /** Public participation is possible: only a gremium without a quorum allows it. */
  readonly publicJoinAllowed: boolean;
  /** The earliest open of a planned meeting with a date (ISO, UTC), else `null`. */
  readonly opensAt: IsoDateTime | null;
  /** Before this point the open is early and needs a confirmation (ISO, UTC), else `null`. */
  readonly confirmUntil: IsoDateTime | null;
}

/** Direction of the meeting timeline relative to *now*. */
export type TimelineDirection = 'past' | 'upcoming';

/** `MeetingPage`. A cursor page of the timeline, wire form. */
export interface MeetingPageWire {
  readonly items: readonly MeetingOutWire[];
  readonly nextCursor?: string | null;
}

/** Meeting timeline page, frontend view. `nextCursor === null` marks the end. */
export interface MeetingPage {
  readonly items: readonly Meeting[];
  readonly nextCursor: string | null;
}

/** Protocol, frontend view. `isFinal` and `isLocked` come from `status`. */
export interface Protocol {
  readonly id: Uuid;
  readonly meetingId: Uuid;
  readonly markdown: string;
  readonly status: 'draft' | 'rendering' | 'final';
  readonly isFinal: boolean;
  /** Not editable. The protocol is final, or the worker renders it (`rendering`). */
  readonly isLocked: boolean;
  readonly pdfUrl: string | null;
  /** Redacted public variant for non-public agenda items. Otherwise null. */
  readonly publicPdfUrl: string | null;
  readonly sentAt: IsoDateTime | null;
  /** Held back from the public protocol page (only matters for a public gremium). */
  readonly publicWithheld?: boolean;
  /** The gremium publishes its final protocols on the public protocol page. */
  readonly gremiumProtocolsPublic?: boolean;
}

/**
 * Toggle for a notification kind (`GET/PUT /notifications/preferences`). The account popout
 * offers it as self service.
 */
export interface NotificationPreference {
  readonly kind: string;
  readonly enabled: boolean;
}

/**
 * An active OAuth grant of the logged-in user. It is an agent or MCP token. The account popout
 * offers the grants as self service.
 */
export interface OAuthGrant {
  readonly id: string;
  readonly clientId: string;
  readonly scope: string;
  readonly createdAt: IsoDateTime | null;
  /**
   * Every new token expires (90 days at most). `null` comes only from a token of the time
   * before the cap; the pages show a dash, never "Läuft nie ab".
   */
  readonly accessExpiresAt: IsoDateTime | null;
  readonly refreshExpiresAt: IsoDateTime | null;
}

/** MCP setup snippet and metadata. GET /mcp/config. */
export interface McpSetup {
  readonly mcpServers: Readonly<Record<string, unknown>>;
  readonly baseUrl: string;
  readonly clientId: string;
  readonly scopesSupported: readonly string[];
  readonly install: string;
  readonly note: string;
}

/** A scope row in the consent screen. `held` means the user holds the permission. */
export interface ConsentScope {
  readonly key: string;
  readonly held: boolean;
}

/** Pending authorize request for the consent screen. */
export interface ConsentRequest {
  readonly clientId: string;
  readonly canUseMcp: boolean;
  readonly requestedScopes: readonly ConsentScope[];
  readonly lifetimes: readonly string[];
  readonly defaultLifetime: string;
}

/** What kind of record a search hit points at. Stable keys, never translated text. */
export type SearchKind =
  | 'application'
  | 'meeting'
  | 'invoice'
  | 'expense'
  | 'budget'
  | 'gremium'
  | 'principal'
  | 'ticket'
  | 'todo'
  | 'event';

/**
 * One row of the global search (`GET /api/search`).
 *
 * Deliberately flat: the palette renders a line, a line under it, and somewhere to go,
 * without knowing the shape of an application, an invoice or a meeting. `url` is always
 * an app-relative route the client has.
 */
export interface SearchHit {
  readonly kind: SearchKind;
  readonly id: string;
  readonly title: string;
  readonly subtitle: string | null;
  readonly url: string;
  /** Applications only. The row badges it, so an archived hit is not read as current. */
  readonly archived?: boolean;
}

/** Everything found for one query, in one round trip. */
export interface SearchResults {
  readonly hits: readonly SearchHit[];
  /** At least one source had more matches than its cap, so this is not everything. */
  readonly truncated: boolean;
  /** Sources that errored. The search degrades rather than returning nothing. */
  readonly failed: readonly string[];
}

/** Admitted guests vote (`vote`) or only follow the meeting (`watch`). */
export type GuestsMode = 'vote' | 'watch';

/** The state of a join request or of a guest. */
export type GuestStatus = 'pending' | 'admitted' | 'rejected' | 'removed' | 'left';

/** `MeetingGuest`: one join request or guest, for the meeting lead. */
export interface MeetingGuest {
  readonly id: Uuid;
  /** The pseudonym number ("Gast 3"), 1-based per meeting. */
  readonly number: number;
  /** `null` once pseudonymized (left, withdrawn, protocol final): show "Gast {number}". */
  readonly displayName: string | null;
  /** `expired` comes only with a `guest_updated` event: the row is gone (a voided request). */
  readonly status: GuestStatus | 'expired';
  readonly requestedAt: IsoDateTime;
  readonly decidedAt: IsoDateTime | null;
  readonly decidedByName: string | null;
  readonly admittedAt: IsoDateTime | null;
}

/** The QR matrix without a quiet zone: `size` rows of `size` characters `0`/`1`. */
export interface QrMatrix {
  readonly size: number;
  readonly rows: readonly string[];
}

/** `JoinLink`: the join code, the absolute join URL and its QR matrix. */
export interface JoinLink {
  readonly joinCode: string;
  readonly joinUrl: string;
  readonly qr: QrMatrix;
}

/** `PublicMeetingHead`: what the join page shows before the admission. */
export interface PublicMeetingHead {
  readonly code: string;
  readonly title: string;
  readonly gremiumName: string | null;
  readonly date: string | null;
  readonly startTime: string | null;
  readonly status: MeetingStatus;
  readonly startedAt: IsoDateTime | null;
  readonly guestsMode: GuestsMode;
}

/** One agenda item of the guest view. A non-public item carries its title, never a body. */
export interface GuestAgendaItem {
  readonly id: Uuid;
  readonly position: number;
  readonly title: string | null;
  readonly kind: 'application' | 'freetext';
  readonly nonPublic: boolean;
  readonly body: string | null;
  /** The done mark ("TOP abhaken"). Always `false` for a non-public item. */
  readonly done: boolean;
}

/** One vote of a public item, as an admitted guest sees it. */
export interface GuestVote extends ElectionFields {
  readonly id: Uuid;
  readonly agendaItemId: Uuid | null;
  readonly question: string | null;
  readonly options: readonly string[];
  readonly status: 'open' | 'closed';
  readonly secret: boolean;
  readonly majorityRule: MajorityRule;
  readonly guestsVote: boolean;
  readonly quorum: Quorum | null;
  readonly openedAt: IsoDateTime | null;
  readonly closedAt: IsoDateTime | null;
  readonly result: VoteResult | null;
  readonly failedReason: 'quorum' | 'majority' | null;
  readonly tally: {
    readonly counts: Readonly<Record<string, number>>;
    readonly voted: number;
    readonly present: number;
    readonly revealed: boolean;
    readonly leading: string | null;
    readonly presentMembers: number | null;
    readonly presentGuests: number | null;
  };
  readonly myBallot: MyBallot;
  readonly canCast: boolean;
}

/** The participant view of an admitted guest. */
export interface GuestView {
  readonly currentAgendaItemId: Uuid | null;
  readonly presentMembers: number;
  readonly admittedGuests: number;
  readonly agenda: readonly GuestAgendaItem[];
  readonly votes: readonly GuestVote[];
}

/** `GuestMe`: the own request or participation of this device. */
export interface GuestMe {
  readonly guestId: Uuid;
  readonly number: number;
  readonly displayName: string | null;
  readonly status: GuestStatus;
  /** Seconds until a new request is possible (rejected, removed), else `null`. */
  readonly retryAfter: number | null;
  readonly meeting: PublicMeetingHead;
  readonly view: GuestView | null;
}

/** `GET /committees/{id}/meeting-defaults`: what a new meeting of the gremium allows. */
export interface MeetingDefaults {
  readonly publicJoinAllowed: boolean;
  readonly quorumPercent: number | null;
}
