/**
 * API-DTOs — abgeleitet aus den OpenAPI-Contracts (sds/api.md §2/§5).
 * Single Source of Truth bleibt das Backend-OpenAPI; diese Typen sind die
 * FE-seitige Spiegelung für den typisierten API-Client. Bei Contract-Änderung
 * → abstimmen (tasks.md §Konventionen), nicht einseitig brechen.
 *
 * Aufbau (T-40, Issue #17):
 *  - **`*Wire`-Typen** spiegeln das Backend-JSON **1:1** (T-12 `_CamelModel`:
 *    camelCase-Aliase via `by_alias`). Sie werden **nicht** direkt in Components
 *    konsumiert, sondern in der `ApiClient`-Schicht über `mappers.ts` in die
 *    FE-View-Modelle übersetzt.
 *  - **View-Modelle** (`Application`, `ApplicationComment`, …) sind die
 *    aufbereiteten, FE-freundlichen Shapes (i18n-Label bereits aufgelöst,
 *    Bool-Komfortfelder). Sie sind das, was Components/Templates sehen.
 *  - **`*Body`-Typen** sind Request-Bodies in der camelCase-Wire-Form.
 */

export type Uuid = string;
export type IsoDateTime = string;
export type Lang = 'de' | 'en';

/** Konfigurierbarer mehrsprachiger Text (`*_i18n`-JSONB, overview §5). */
export type I18nMap = Record<string, string>;

/** Öffentliche (auth-freie) aktive Branding-Config (#18) — bewusst lose typisiert:
 *  das FE liest hieraus nur die Freitexte (z. B. `applyInfo`). */
export interface PublicSiteConfig {
  version: number;
  branding?: {
    freetexts?: Partial<
      Record<'loginHint' | 'welcome' | 'support' | 'emailFooter' | 'applyInfo', I18nMap>
    >;
  } | null;
}

/** Einheitliches Problem-Objekt (RFC-9457-nah, api.md §2). */
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
 * Principal (OIDC) inkl. Rollen/Permissions/Gruppen — GET /api/auth/me.
 * Feldnamen spiegeln das Backend-`MeOut` (auth/schemas.py) 1:1. `MeOut` ist ein
 * **reines** `BaseModel` (kein `_CamelModel`) → `display_name` bleibt snake_case.
 */
/** Schlanke Gremium-Referenz (Mitgliedschaft eines Principals, #5). */
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
  /** Gremien, in denen der Principal Mitglied ist (#5) — Basis für »Meine Gremien«. */
  gremien?: GremiumRef[];
  /** Gremien, die der Principal verwaltet (Gremium-Rolle mit `session.manage`). */
  session_manage_gremien?: Uuid[];
  /** ≥1 Kostenstelle ist einem Mitglieds-Gremium zugeordnet (#budget-scope). */
  has_scoped_budget_view?: boolean;
  /** Principal steht in ≥1 Stellvertreter-Pool (#7) — Sitzungs-Timeline sichtbar. */
  in_substitute_pool?: boolean;
}

/** Antwort von POST /api/auth/logout — RP-Initiated-Logout-URL (OIDC) oder null. */
export interface LogoutOut {
  logout_url: string | null;
}

/** Einheitliche Listen-Hülle (Offset-Paging, overview §5 / api.md). */
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
  /** Kostenstelle (Budget-Baum) inkl. Unterbaum. */
  budget?: Uuid;
  q?: string;
  amountMin?: number;
  amountMax?: number;
  createdFrom?: string;
  createdTo?: string;
  sort?: 'createdAt' | 'amount';
  order?: 'asc' | 'desc';
  /** Nur eigene Anträge — erzwingt den Owner-Filter auch mit `application.read`. */
  mine?: boolean;
  limit?: number;
  offset?: number;
}

// =========================================================================== //
// Wire-DTOs — exakte Spiegelung des Backend-JSON (T-12 `_CamelModel`).         //
// =========================================================================== //

/** `StateOut` (applications/schemas.py) — `label` ist eine **i18n-Map**. */
export interface StateOutWire {
  id: Uuid;
  key: string;
  label: I18nMap;
  /** Anzeigefarbe des State-Badges (Hex), optional. */
  color?: string | null;
  editAllowed: boolean;
  /** State-Art (#28): normal|vote. */
  kind?: string;
}

/** `ApplicantOut` — PII, nur für Berechtigte gefüllt. */
export interface ApplicantOutWire {
  email?: string | null;
  name?: string | null;
}

/** `ApplicationOut` — Antrag-Detail. */
export interface ApplicationOutWire {
  id: Uuid;
  typeId: Uuid;
  state?: StateOutWire | null;
  gremiumId?: Uuid | null;
  budgetPotId?: Uuid | null;
  budgetId?: Uuid | null;
  amount?: string | null;
  currency?: string | null;
  data: Record<string, unknown>;
  version: number;
  lang?: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  applicant?: ApplicantOutWire | null;
  canEdit?: boolean;
}

/** `ApplicationListItem` — Listen-Eintrag (kein `data`/`applicant`). */
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

/** `ApplicationCreated` — 201-Antwort auf `POST /applications` (nur die ID). */
export interface ApplicationCreatedWire {
  applicationId: Uuid;
}

/** Anwesenheits-Status eines Mitglieds in einer Sitzung (#Meetings). */
export type AttendanceStatus = 'present' | 'excused' | 'absent';

/** `AttendanceOut` — Anwesenheit eines Gremium-Mitglieds (GET/PUT …/attendance). */
export interface Attendance {
  principalId: Uuid;
  displayName: string | null;
  email: string | null;
  /** `null` = noch nicht erfasst. */
  status: AttendanceStatus | null;
  source: 'self' | 'lead' | null;
  /** Ist das der anfragende Nutzer (für die Selbst-Markierung)? */
  isSelf: boolean;
}

/** `AgendaItemOut` — ein TOP: zugeordneter Antrag oder Freitext (Tagesordnung, #10/#58). */
export interface AgendaItem {
  id: Uuid;
  /** `null` bei einem Freitext-TOP (ohne Antrag). */
  applicationId: Uuid | null;
  title: string | null;
  /** Markdown-Text dieses TOP (pro-TOP-Editor, #58). */
  body?: string | null;
  position: number;
  stateLabel?: I18nMap | null;
}

/** `AssignableApplicationOut` — Antrag in einem Abstimmungs-State, noch nicht auf der TO. */
export interface AssignableApplication {
  applicationId: Uuid;
  title: string | null;
  stateLabel?: I18nMap | null;
}

/** `AltchaChallengeOut` — server-signierte PoW-Challenge (GET /altcha/challenge). */
export interface AltchaChallenge {
  algorithm: string;
  challenge: string;
  salt: string;
  signature: string;
  maxnumber: number;
}

/** `TimelineEventOut` — Status-Übergang in der Timeline. */
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

/** `CommentOut` — echte Backend-Feldnamen: `author`/`authorKind`/`visibility`/`at`. */
export interface CommentOutWire {
  id: Uuid;
  author?: string | null;
  authorKind: CommentAuthorKind;
  body: string;
  visibility: CommentVisibility;
  at: IsoDateTime;
}

/** `ApplicationTypeListItem` (application_types/schemas.py). */
export interface ApplicationTypeListItemWire {
  id: Uuid;
  name: string;
  hasBudget: boolean;
  active: boolean;
  activeFormVersionId?: Uuid | null;
  /** Admin-Zusatzfelder (nur bei Berechtigung gefüllt). */
  key?: string | null;
  gremiumId?: Uuid | null;
}

/** `TransitionOut` (flow/schemas.py) — `label` ist eine i18n-Map. */
export interface TransitionOutWire {
  id: Uuid;
  fromStateId: Uuid;
  toStateId: Uuid;
  label: I18nMap;
  /** Optionale Farbe für den Entscheidungs-Button (#flow). */
  color?: string | null;
}

/** Eine Feld-Änderung im Versions-Diff (`FieldChange`, applications/diff.py). */
export interface FieldChangeWire {
  old: unknown;
  new: unknown;
}

/**
 * Struktur-Diff zweier `data`-Snapshots (`DataDiff`, applications/diff.py):
 * `added`/`removed` sind Feldwert-Maps, `changed` mappt Schlüssel → `{old,new}`.
 * Verschachtelte Felder werden **wertweise als Ganzes** verglichen (kein
 * rekursives Zell-Diff) — robust gegen heterogene Tabellen/Objekte (T-12).
 */
export interface DataDiffWire {
  added: Record<string, unknown>;
  removed: Record<string, unknown>;
  changed: Record<string, FieldChangeWire>;
}

/** `VersionOut` (applications/schemas.py) — eine Submission-Version + Diff. */
export interface VersionOutWire {
  version: number;
  data: Record<string, unknown>;
  diff?: DataDiffWire | null;
  changedBy?: string | null;
  at: IsoDateTime;
}

/**
 * `AttachmentOut` (files/schemas.py, T-13) — Anhang-Metadaten. **Reines
 * `BaseModel`** (kein `_CamelModel`) → `is_comparison_offer` bleibt snake_case.
 * `scanned` = ClamAV-Lauf **abgeschlossen** (nicht „sauber"!): das Scan-Ergebnis
 * (`scan_result`) wird bewusst nicht exponiert (security.md §6), Befund ⇒ Objekt
 * gelöscht. Sauber-vs-Befund klärt sich erst beim Download (200 vs. 409).
 */
export interface AttachmentOutWire {
  id: Uuid;
  filename: string;
  mime: string;
  size: number;
  scanned: boolean;
  is_comparison_offer: boolean;
}

/** `SignedUrlOut` (files/schemas.py) — kurzlebige MinIO-URL + Restlaufzeit (s). */
export interface SignedUrlOutWire {
  url: string;
  expiresIn: number;
}

// --- Request-Bodies (camelCase-Wire-Form) ---------------------------------- //

/** Body für `POST /applications` (`ApplicationCreate`, by_alias). */
export interface ApplicationCreateBody {
  typeId: Uuid;
  budgetPotId?: Uuid | null;
  data: Record<string, unknown>;
  // Optional: für eingeloggte Nutzer:innen leitet das Backend die Identität aus dem
  // Account ab (#24); anonyme Einreichung erzwingt sie serverseitig.
  applicantEmail?: string | null;
  applicantName?: string | null;
  lang: Lang;
  altcha?: string | null;
}

/** Body für `POST /applications/{id}/comments` (`CommentCreate`). */
export interface CommentCreateBody {
  body: string;
  visibility: CommentVisibility;
}

/** Body für `POST /applications/{id}/transition` (`TransitionRequest`). */
export interface TransitionRequestBody {
  transitionId: Uuid;
  note?: string | null;
}

/** `TransitionResult` — 200-Antwort eines erfolgreichen Übergangs. */
export interface TransitionResult {
  newStateId: Uuid;
  statusEventId: Uuid;
  dispatchedActions: string[];
}

// =========================================================================== //
// View-Modelle — FE-freundlich, i18n bereits aufgelöst (Output von mappers.ts). //
// =========================================================================== //

/** Status eines Antrags mit **aufgelöstem** Label (für die aktuelle `lang`). */
export interface ApplicationState {
  id: Uuid;
  key: string;
  label: string;
  /** Anzeigefarbe des State-Badges (Hex), optional. */
  color?: string | null;
  editAllowed: boolean;
  /** State-Art (#28): normal|vote. */
  kind: string;
}

export interface Applicant {
  email: string | null;
  name: string | null;
}

export interface Application {
  id: Uuid;
  typeId: Uuid;
  state: ApplicationState | null;
  gremiumId: Uuid | null;
  budgetPotId: Uuid | null;
  budgetId: Uuid | null;
  amount: string | null;
  currency: string | null;
  data: Record<string, unknown>;
  version: number;
  lang: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  applicant: Applicant | null;
  /** Darf der/die Anfragende bearbeiten/löschen (Verwalter:in oder Ersteller:in, #24)? */
  canEdit: boolean;
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

/** Ergebnis von `POST /applications` (FE-View). */
export interface ApplicationCreated {
  applicationId: Uuid;
}

/** Timeline-Eintrag (FE-View) — `label` aus `toState` aufgelöst. */
export interface TimelineEntry {
  toStateId: Uuid;
  toState: ApplicationState | null;
  label: string;
  actor: string | null;
  at: IsoDateTime;
  note: string | null;
}

/** Kommentar (FE-View) — `isPublic` aus `visibility` abgeleitet. */
export interface ApplicationComment {
  id: Uuid;
  author: string | null;
  authorKind: CommentAuthorKind;
  body: string;
  visibility: CommentVisibility;
  isPublic: boolean;
  at: IsoDateTime;
}

/** Antragstyp (FE-View) für die Wizard-Auswahl. */
export interface ApplicationType {
  id: Uuid;
  name: string;
  active: boolean;
  hasBudget: boolean;
  activeFormVersionId: Uuid | null;
  key: string | null;
  gremiumId: Uuid | null;
}

/** Verfügbarer Übergang (FE-View) — `label` aufgelöst. */
export interface Transition {
  id: Uuid;
  fromStateId: Uuid;
  toStateId: Uuid;
  label: string;
  /** Optionale Farbe für den Entscheidungs-Button (#flow); null = Default. */
  color: string | null;
}

/** Eine geänderte Feldzelle (FE-View) — `key` aus der Diff-Map herausgezogen. */
export interface FieldChange {
  key: string;
  old: unknown;
  new: unknown;
}

/**
 * Versions-Diff (FE-View) — die Backend-Maps (`added`/`removed`/`changed`)
 * sind hier in iterierbare, schlüsseltragende Listen aufgelöst, damit Templates
 * direkt mit `@for` darüber rendern können.
 */
export interface DataDiff {
  added: { key: string; value: unknown }[];
  removed: { key: string; value: unknown }[];
  changed: FieldChange[];
}

/** Eine Submission-Version (FE-View) für die Historie/Diff-Ansicht. */
export interface ApplicationVersion {
  version: number;
  data: Record<string, unknown>;
  diff: DataDiff | null;
  changedBy: string | null;
  at: IsoDateTime;
}

/**
 * Scan-Zustand eines Anhangs (FE-View). Aus dem Contract ableitbar:
 * - `scanning`    — `scanned=false`: ClamAV läuft noch, kein Download (→ 409).
 * - `clean`       — `scanned=true`: Scan fertig; Download grundsätzlich möglich.
 * - `quarantined` — clientseitig gesetzt, wenn der Download mit **409** abgewiesen
 *   wird (Befund/Quarantäne) — die Metadaten allein verraten das nicht.
 */
export type ScanState = 'scanning' | 'clean' | 'quarantined';

/** Anhang (FE-View) — `isComparisonOffer` camelCase, `scanState` abgeleitet. */
export interface Attachment {
  id: Uuid;
  filename: string;
  mime: string;
  size: number;
  scanned: boolean;
  isComparisonOffer: boolean;
  scanState: ScanState;
}

/** Signierte Download-URL (FE-View). */
export interface SignedUrl {
  url: string;
  expiresIn: number;
}

/** FE-Eingabe für einen neuen Antrag → via Mapper zu `ApplicationCreateBody`. */
export interface NewApplication {
  typeId: Uuid;
  budgetPotId?: Uuid | null;
  data: Record<string, unknown>;
  // Null für eingeloggte Nutzer:innen — das Backend leitet Identität/Altcha ab (#24).
  applicantEmail?: string | null;
  applicantName?: string | null;
  lang: Lang;
  altcha?: string | null;
}

// --- Form-Definition (config_schemas §5.1) — Spiegel von FormFieldDef ---------

export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'currency'
  | 'date'
  | 'select'
  | 'multiselect'
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
  /** `positions`: Mindestzahl Vergleichsangebote je Position / Mindestzahl Positionen. */
  minOffers?: number;
  minPositions?: number;
}

/** Eine Feld-Definition der effektiven Form (camelCase wie das OpenAPI-by_alias). */
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
  isPromoted?: boolean;
  promoteTarget?: string;
}

export interface FormSection {
  key: string;
  label: I18nMap;
  fields: FormFieldDef[];
}

/** Effektive Form-Definition — GET /api/application-types/{id}/form (forms §5.7). */
export interface EffectiveForm {
  applicationTypeId: Uuid;
  formVersionId: Uuid;
  budgetPotId?: Uuid | null;
  sections: FormSection[];
}

// --- Magic-Link (api.md §1) ---------------------------------------------------

/**
 * Antwort von POST /api/auth/magic-link/verify (`MagicLinkVerifyOut`,
 * auth/schemas.py — T-10). Reines `BaseModel` (kein `_CamelModel`) → Feldnamen
 * bleiben snake_case (`application_id`). Die Applicant-Session läuft
 * **ausschließlich** über ein HttpOnly-Cookie (security.md §1) — **kein**
 * Session-Token im Body/JS.
 */
export interface MagicLinkVerifyResult {
  application_id: Uuid;
  scope: 'edit' | 'view';
}

// --- Voting (api.md »voting«, §4; config_schemas.VoteConfig — T-15) -----------

export type MajorityRule = 'simple' | 'absolute' | 'two_thirds';
/** `cancelled` — Antrag hat den vote-State manuell verlassen (Wahl abgebrochen). */
export type VoteStatus = 'draft' | 'open' | 'closed' | 'cancelled';
export type VoteResult = 'passed' | 'rejected' | 'tie';

/** Beschlussfähigkeits-Schwelle (config_schemas.Quorum). */
export interface Quorum {
  type: 'count' | 'percent';
  value: number;
}

/**
 * Abstimmungs-Konfiguration (`VoteConfig`, config_schemas.py). Felder kommen
 * camelCase über das Backend-`_CamelModel`; Defaults spiegeln die Pydantic-
 * Defaults (`abstainCountsQuorum`/`allowChange` true, `secret` false).
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
 * Aggregiertes Zwischen-/Endergebnis (`TallyOut`). Bei `secret` enthält der
 * Server nur `counts` — **nie** einzelne Stimmende (api.md §4).
 */
export interface Tally {
  counts: Record<string, number>;
  eligible: number;
  quorumMet: boolean;
  leading: string | null;
  result?: VoteResult | null;
}

/**
 * Vote-State + Tally — GET /api/votes/{id} (`VoteOut`). Reines `_CamelModel`,
 * daher 1:1 als View-Modell verwendbar (kein i18n-Label, Optionen sind
 * Roh-Keys, die das FE über `vote.option.*` übersetzt).
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

/** Antwort auf eine angenommene Stimme — POST /api/votes/{id}/ballot. */
export interface BallotResult {
  status: 'cast' | 'changed';
}

// =========================================================================== //
// Meetings + Protokoll (T-33) — api.md livevote/meetings + protocol.            //
// Wire-Form camelCase (T-12 `_CamelModel`); Backend-Modul folgt mit T-16/T-22,  //
// FE arbeitet bis dahin gegen den Mock (network-plan §4).                       //
// =========================================================================== //

/** Sitzungs-Status (api.md §4 `meeting_state.status`); BE-Enum: `planned|live|closed`. */
export type MeetingStatus = 'planned' | 'live' | 'closed';
/** Status eines Votes innerhalb einer Sitzung. */
/** `cancelled` — Antrag hat den vote-State manuell verlassen (Wahl abgebrochen). */
export type MeetingVoteStatus = 'pending' | 'open' | 'closed' | 'cancelled';

/** `MeetingVoteOut` — Vote-Zusammenfassung im Sitzungs-State (GET /meetings/{id}). */
export interface MeetingVoteOutWire {
  id: Uuid;
  /** `null` = generische Beschlussfrage (Freitext-TOP), kein Antrag. */
  applicationId?: Uuid | null;
  /** An welchen TOP die Abstimmung gebunden ist (Gruppierung im FE). */
  agendaItemId?: Uuid | null;
  /** Antrags-Titel (vom Backend mitgeliefert; sonst aus dem Antrag aufzulösen). */
  title?: string | null;
  /** Beschlussfrage der (Live-)Abstimmung — fürs Protokoll (#Meetings). */
  question?: string | null;
  /** Optionen (für die Stimmabgabe). */
  options?: string[] | null;
  status: MeetingVoteStatus;
  /** Endergebnis (z. B. `accepted`/`rejected`), erst nach `closed`. */
  result?: string | null;
  counts?: Record<string, number> | null;
  leading?: string | null;
  closesAt?: IsoDateTime | null;
  voted?: number | null;
  present?: number | null;
  revealed?: boolean | null;
  /** Grund einer Ablehnung: `quorum` = Quorum verfehlt, `majority` = Mehrheit verfehlt. */
  failedReason?: 'quorum' | 'majority' | null;
}

// (failedReason auf MeetingVoteOutWire ergänzt — Backend liefert den Grund nach Close.)

/** `MeetingOut` — Sitzungs-State + Votes (GET /meetings/{id}). */
export interface MeetingOutWire {
  id: Uuid;
  title: string;
  date?: string | null;
  startTime?: string | null;
  status: MeetingStatus;
  activeApplicationId?: Uuid | null;
  gremiumId?: Uuid | null;
  gremiumName?: string | null;
  votes: MeetingVoteOutWire[];
  /** Verknüpftes Protokoll (falls bereits angelegt). */
  protocolId?: Uuid | null;
  createdAt: IsoDateTime;
  protokollantId?: Uuid | null;
  protokollantName?: string | null;
  /** Master-Flag: darf der Nutzer die Sitzung führen (Protokoll/TOPs/Status)? */
  canControl?: boolean;
  /** Sitzung verwalten (anlegen/planen/Protokollant zuweisen). */
  canManage?: boolean;
  /** Protokoll/TOPs schreiben (zugewiesener Protokollant oder Verwalter). */
  canWrite?: boolean;
  /** Beschlussfragen öffnen/schließen. */
  canManageVotes?: boolean;
  /** In dieser Sitzung stimmberechtigt (Rolle mit vote.cast). */
  canVote?: boolean;
}

/** `ProtocolOut` — Sitzungsprotokoll (POST /meetings/{id}/protocol, PATCH /protocols/{id}). */
export interface ProtocolOutWire {
  id: Uuid;
  meetingId: Uuid;
  markdown: string;
  /** `rendering` = finalize angestoßen, der Worker rendert das PDF im Hintergrund. */
  status: 'draft' | 'rendering' | 'final';
  /** Ergebnis-Link nach `finalize` (PDF in MinIO). */
  pdfUrl?: string | null;
  sentAt?: IsoDateTime | null;
}

// --- Request-Bodies (camelCase-Wire-Form) ---------------------------------- //

/** Body für `POST /meetings` (`MeetingCreate`). */
export interface MeetingCreateBody {
  title: string;
  gremiumId?: Uuid | null;
  /** Geplantes Sitzungsdatum (`YYYY-MM-DD`), optional. */
  date?: string | null;
  /** Geplante Uhrzeit (`HH:mm`), optional (#34). */
  startTime?: string | null;
  /** Zugewiesener Protokollant (Mitglied des Gremiums), optional. */
  protokollantId?: Uuid | null;
}

/** Body für `PATCH /meetings/{id}` — Status, aktiven Antrag, Datum und/oder Protokollant. */
export interface MeetingPatchBody {
  status?: MeetingStatus;
  activeApplicationId?: Uuid | null;
  /** Geplantes Sitzungsdatum (`YYYY-MM-DD`); für Vorab-Terminierung geplanter Sitzungen. */
  date?: string | null;
  /** Geplante Uhrzeit (`HH:mm`) (#34). */
  startTime?: string | null;
  /** Protokollant (um)setzen. */
  protokollantId?: Uuid | null;
}

/** Body für `PATCH /protocols/{id}` — Markdown aktualisieren. */
export interface ProtocolPatchBody {
  markdown: string;
}

/** Body für `POST /protocols/{id}/votes` — Abstimmungen einbetten. */
export interface ProtocolVotesBody {
  voteIds: Uuid[];
}

// --- View-Modelle ---------------------------------------------------------- //

/** Vote-Zusammenfassung (FE-View) — `null`-Defaults normalisiert. */
export interface MeetingVote {
  id: Uuid;
  /** `null` = generische Beschlussfrage (Freitext-TOP). */
  applicationId: Uuid | null;
  /** TOP, an den die Abstimmung gebunden ist. */
  agendaItemId: Uuid | null;
  title: string | null;
  question: string | null;
  options: string[];
  status: MeetingVoteStatus;
  result: string | null;
  counts: Record<string, number> | null;
  leading: string | null;
  closesAt: IsoDateTime | null;
  /** Teilnahme-Fortschritt: abgestimmte vs. anwesende Mitglieder. `revealed` = ob
   *  `counts`/`leading` sichtbar sind (sonst nur Fortschritt, #vote-progress). */
  voted: number;
  present: number;
  revealed: boolean;
  /** Grund einer Ablehnung: `quorum` = Quorum verfehlt, `majority` = Mehrheit verfehlt. */
  failedReason: 'quorum' | 'majority' | null;
}

/** Sitzung (FE-View). */
export interface Meeting {
  id: Uuid;
  title: string;
  /** Geplantes Sitzungsdatum (`YYYY-MM-DD`) oder `null`. */
  date: string | null;
  /** Geplante Uhrzeit (`HH:mm`) oder `null` (#34). */
  startTime: string | null;
  status: MeetingStatus;
  activeApplicationId: Uuid | null;
  gremiumId: Uuid | null;
  /** Name des zugehörigen Gremiums (für Timeline-Anzeige, #104). */
  gremiumName: string | null;
  votes: MeetingVote[];
  protocolId: Uuid | null;
  createdAt: IsoDateTime;
  protokollantId: Uuid | null;
  protokollantName: string | null;
  /** Master-Flag: darf der Nutzer die Sitzung führen (Protokoll/TOPs/Status)? */
  canControl: boolean;
  /** Sitzung verwalten (anlegen/planen/Protokollant zuweisen). */
  canManage: boolean;
  /** Protokoll/TOPs schreiben (zugewiesener Protokollant oder Verwalter). */
  canWrite: boolean;
  /** Beschlussfragen öffnen/schließen. */
  canManageVotes: boolean;
  /** In dieser Sitzung stimmberechtigt. */
  canVote: boolean;
}

/** Richtung der Sitzungs-Timeline relativ zu *jetzt* (#104). */
export type TimelineDirection = 'past' | 'upcoming';

/** `MeetingPage` — Cursor-Seite der Timeline (Wire). */
export interface MeetingPageWire {
  items: MeetingOutWire[];
  nextCursor?: string | null;
}

/** Sitzungs-Timeline-Seite (FE-View); `nextCursor === null` ⇒ Ende erreicht. */
export interface MeetingPage {
  items: Meeting[];
  nextCursor: string | null;
}

/** Protokoll (FE-View) — `isFinal`/`isLocked` aus `status` abgeleitet. */
export interface Protocol {
  id: Uuid;
  meetingId: Uuid;
  markdown: string;
  status: 'draft' | 'rendering' | 'final';
  isFinal: boolean;
  /** Nicht editierbar: final **oder** der Worker rendert gerade (`rendering`). */
  isLocked: boolean;
  pdfUrl: string | null;
  sentAt: IsoDateTime | null;
}

// =========================================================================== //
// Benachrichtigungs-Präferenzen (#4-2) — Self-Service über das Konto-Popout.    //
// =========================================================================== //

/** Schalter einer Benachrichtigungs-Art (`GET/PUT /notifications/preferences`). */
export interface NotificationPreference {
  kind: string;
  enabled: boolean;
}

// =========================================================================== //
// OAuth-Grants + MCP-Setup (#MCP) — Self-Service über das Konto-Popout.          //
// =========================================================================== //

/** Ein aktiver OAuth-Grant (Agent/MCP-Token) des eingeloggten Nutzers. */
export interface OAuthGrant {
  id: string;
  clientId: string;
  scope: string;
  createdAt: IsoDateTime | null;
  accessExpiresAt: IsoDateTime;
  refreshExpiresAt: IsoDateTime | null;
}

/** Fertiger MCP-Setup-Schnipsel + Metadaten (GET /mcp/config). */
export interface McpSetup {
  mcpServers: Record<string, unknown>;
  baseUrl: string;
  clientId: string;
  scopesSupported: string[];
  install: string;
  note: string;
}

/** Eine im Consent angefragte Scope-Zeile (held = Nutzer besitzt das Recht). */
export interface ConsentScope {
  key: string;
  held: boolean;
}

/** Schwebender Authorize-Request für den Consent-Screen (#MCP). */
export interface ConsentRequest {
  clientId: string;
  canUseMcp: boolean;
  requestedScopes: ConsentScope[];
  lifetimes: string[];
  defaultLifetime: string;
}
