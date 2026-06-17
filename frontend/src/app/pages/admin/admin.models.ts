/**
 * Admin-Config-DTOs (T-34) — Spiegel der admin-API (sds/api.md §3 »admin«) und
 * der Config-Schemas (config_schemas §5). camelCase wie das Backend-`_CamelModel`.
 *
 * Quelle der Wahrheit bleibt das Backend-OpenAPI. **Status der Endpunkte (Stand
 * Branch-Basis `origin/main` bc275a8): T-24 (admin-API) ist NICHT gemergt** —
 * `app/modules/admin` enthält nur Tabellen, keine Router. Diese Typen + der
 * `AdminApiService` sind daher gegen den Contract (api.md) gebaut; im Mock-Modus
 * (`USE_MOCK_API`) liefert ein In-Memory-Store Daten, damit die UIs entwickel-
 * und testbar sind. Beim Merge von T-24 nur die Mock-Schicht entfernen.
 *
 * Branding/Site-Config (#21) ist **nicht** Teil der SDS — der Contract hier ist
 * eine T-34-Festlegung (`/api/admin/site-config`). TODO(T-24/#21): mit Backend
 * abstimmen, sobald der Endpunkt existiert.
 */
import type { FormFieldDef, I18nMap, Uuid } from '@core/api/models';

// --- Flow-Graph (config_schemas §5.2) ---------------------------------------

/** State-Art im globalen Flow (#28-Redesign): nur noch normal + vote. */
export type StateKind = 'normal' | 'vote';

/** Config eines States je nach `kind`. Leeres Objekt für `normal`. */
export interface StateConfig {
  /** vote: Gremium, das abstimmt. */
  gremiumId?: string;
  /**
   * Schlüssel einer benannten Deadline-Policy (#13): beim Betreten des States legt
   * der Server eine Frist an, die der `deadlinePassed`-Übergang des States feuert.
   */
  deadlinePolicyKey?: string;
}

export interface StateDef {
  key: string;
  label: I18nMap;
  /** Anzeigefarbe des State-Badges (Hex), optional. */
  color?: string | null;
  editAllowed?: boolean;
  isInitial?: boolean;
  /** Endzustand (#PII-Re-Add): terminale Anträge sind aufbewahrungs-/anonymisierbar. */
  isTerminal?: boolean;
  /** State-Art (#28); fehlt ⇒ `normal`. */
  kind?: StateKind | null;
  /** Kind-spezifische Konfiguration (#28). */
  config?: StateConfig | null;
}

/** Ergebnis-Zweig eines vote-States (#28): pass/fail. */
export type TransitionBranch = 'pass' | 'fail';

export interface TransitionDef {
  from: string;
  to: string;
  label?: I18nMap | null;
  /** Optionale Farbe (#flow): färbt Pfeil im Editor + Entscheidungs-Button im Antrag. */
  color?: string | null;
  guard?: Guard | null;
  actions?: ActionDef[];
  order?: number | null;
  /** Automatischer Übergang (#8): feuert ohne Nutzer-Aktion, sobald der Guard erfüllt ist. */
  automatic?: boolean;
  /** Ergebnis-Zweig für vote-States (#28): pass/fail. */
  branch?: TransitionBranch | null;
  /** »Erfordert Aktion« (#requires-action): zählt als offene Aufgabe im Tasks-Tab.
   *  Fehlt ⇒ `true`; `false` = rein optionale Aktion. */
  requiresAction?: boolean;
}

/** Visuelle Node-Gruppe (#flow-groups) — reine Editor-Darstellung, die Engine
 *  ignoriert sie. Im Canvas ist eine Gruppe immer EIN beschrifteter Kasten;
 *  ihr Inhalt öffnet sich per Drill-Down (Breadcrumbs). Gruppen sind
 *  schachtelbar über `groupIds`; ein State/eine Gruppe steckt in höchstens
 *  einem Parent. */
export interface FlowGroup {
  id: string;
  name: string;
  stateKeys: string[];
  /** Direkt enthaltene Unter-Gruppen (Schachtelung). */
  groupIds?: string[];
  color?: string | null;
}

/** Optionales Editor-Layout (Knoten-Positionen + Gruppen) — persistiert im Graphen. */
export interface FlowLayout {
  positions?: Record<string, { x: number; y: number }>;
  groups?: FlowGroup[];
}

export interface FlowGraph {
  states: StateDef[];
  transitions: TransitionDef[];
  layout?: FlowLayout | null;
}

// --- Guards (shared/guards.py — Whitelist, #28-Redesign) --------------------

/** Vergleichs-Operatoren des `compare`-Guards (typabhängig zur Laufzeit). */
export type CompareOp = '==' | '!=' | '<' | '<=' | '>' | '>=' | 'in';
export const COMPARE_OPS: readonly CompareOp[] = ['==', '!=', '<', '<=', '>', '>=', 'in'] as const;

/** Bedingungs-Operatoren (auf automatischen + manuellen Übergängen). */
export type GuardConditionOp =
  | 'deadlinePassed'
  | 'applicantRoleIs'
  | 'applicantCommitteeIs'
  | 'budgetIs'
  | 'budgetFitsApplication'
  | 'hasField'
  | 'compare';
/** Akteur-Gates — nur auf **manuellen** Übergängen. */
export type GuardActorOp = 'roleIs' | 'isInCommittee' | 'actorIsApplicant';
export type GuardLeafOperator = GuardConditionOp | GuardActorOp;
export type GuardCombinator = 'and' | 'or' | 'not';

/** Ein einzelner Guard-Knoten (genau ein Operator, wie `validate_guard`). */
export type Guard = Record<string, unknown>;

export const GUARD_CONDITION_OPERATORS: readonly GuardConditionOp[] = [
  'deadlinePassed',
  'applicantRoleIs',
  'applicantCommitteeIs',
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

// --- Actions (#28: webhook/notify/addToNextSession/assignBudget) ------------

export type ActionType = 'webhook' | 'notify' | 'addToNextSession' | 'assignBudget';
export const ACTION_TYPES: readonly ActionType[] = [
  'webhook',
  'notify',
  'addToNextSession',
  'assignBudget',
] as const;

/** Empfänger-Art einer `notify`-Action. */
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

// --- Organisation / RBAC (admin/models.py) ----------------------------------

export interface Gremium {
  id: Uuid;
  name: string;
  slug: string;
  cdVariant: string;
  defaultLang: string;
  allowVoteDelegation: boolean;
  /** Vorlauf (Minuten vor Sitzungsbeginn) für Nicht-Pool-Delegationen; 0 = bis Beginn. */
  delegationLeadMinutes?: number;
  /** Delegation an Nutzer außerhalb von Gremium & Stellvertreter-Pool erlauben. */
  delegationAllowExternal?: boolean;
  /** Default-Quorum (% der Stimmberechtigten, die teilnehmen müssen); null = keins. */
  quorumPercent?: number | null;
}

/** Body für `POST /admin/gremien` (`GremiumCreate`). */
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

/** Body für `PATCH /admin/gremien/{id}` (`GremiumUpdate`) — alle Felder optional. */
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

/** CD-Varianten (pytex) als Dropdown statt Freitext (#18). */
export const CD_VARIANTS: readonly string[] = ['stupa', 'asta', 'echo', 'makers', 'report'];

/** Name → URL-Slug (#18, automatische Generierung). */
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

/** Mail-Template (admin-API `/admin/mail-templates`, #5-4): i18n Subject/Body/HTML. */
export interface MailTemplate {
  /** Builtins (noch nicht überschrieben) haben keine DB-ID (#12). */
  id: Uuid | null;
  key: string;
  subjectI18n: I18nMap;
  bodyI18n: I18nMap;
  bodyHtmlI18n: I18nMap;
  placeholders: Record<string, string>;
  /** 'override' = aus der DB; 'builtin' = unveränderter Katalog-Default. */
  source: 'override' | 'builtin';
}

/** Override per Key anlegen/aktualisieren (#12, Katalog-Merge). */
export interface MailTemplateUpsertBody {
  key: string;
  subjectI18n: I18nMap;
  bodyI18n: I18nMap;
  bodyHtmlI18n: I18nMap;
}

/** Vorschau aus dem Editor-Entwurf (ohne ID, #12). */
export interface MailPreviewPayload {
  subjectI18n: I18nMap;
  bodyI18n: I18nMap;
  bodyHtmlI18n: I18nMap;
  lang: string;
  context: Record<string, unknown>;
}

/** Gerenderte Vorschau eines Templates. */
export interface MailPreview {
  subject: string;
  text: string;
  html?: string | null;
  lang: string;
}

/** OIDC-Gruppe → Rolle(+ optional Gremium) Mapping (admin-API `/group-mappings`, #5-4). */
export interface GroupMapping {
  id: Uuid;
  oidcGroup: string;
  roleId: Uuid;
  gremiumId?: Uuid | null;
}

/** Eingabe zum Anlegen/Ändern eines Group-Mappings. */
export interface GroupMappingBody {
  oidcGroup: string;
  roleId: Uuid;
  gremiumId?: Uuid | null;
}

/** Rollenzuweisung (admin-API `/role-assignments`) — Vertretung/Delegation. */
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

/** Eingabe für eine neue Zuweisung (#72) — optionales tz-aware Gültigkeitsfenster. */
export interface RoleAssignmentInput {
  principalId: Uuid;
  roleId: Uuid;
  gremiumId?: Uuid | null;
  validFrom?: string | null;
  validUntil?: string | null;
  delegateVoting?: boolean;
}

/** OIDC-Principal (Benutzer) inkl. seiner Rollenzuweisungen (admin-API `/principals`). */
export interface AdminPrincipal {
  id: Uuid;
  sub: string;
  email?: string | null;
  displayName?: string | null;
  lastLogin?: string | null;
  /** Aktiv/deaktiviert (#30). */
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

/**
 * Antragstyp (Formular) als Editier-Sicht des NC-Forms-Builders (#13). Spiegelt
 * `ApplicationTypeOut` der Admin-API; `name` ist die i18n-Map (Titel des Formulars).
 */
/** Vergleichsangebote-Regel eines Antragstyps (#5-4). */
export interface ComparisonOffers {
  required: boolean;
  minCount: number;
  thresholdAmount?: string | null;
  as?: 'file' | 'field' | 'both';
}

export interface ApplicationTypeFull {
  id: Uuid;
  name: I18nMap;
  gremiumId?: Uuid | null;
  hasBudget: boolean;
  comparisonOffers?: ComparisonOffers | null;
  /** DSGVO-Aufbewahrung in Monaten; null = globaler Default (#PII-Re-Add). */
  retentionMonths?: number | null;
  activeFormVersionId?: Uuid | null;
}

/** Body für `POST /admin/application-types` — Antragstyp/Formular anlegen (#13). */
export interface ApplicationTypeCreateBody {
  key: string;
  name: I18nMap;
  gremiumId?: Uuid | null;
  hasBudget?: boolean;
}

/** Body für `PATCH /admin/application-types/{id}` — Titel/Gremium/Budget (#13). */
export interface ApplicationTypeUpdateBody {
  name?: I18nMap;
  gremiumId?: Uuid | null;
  hasBudget?: boolean;
  comparisonOffers?: ComparisonOffers | null;
}

/**
 * Aktuelle Form-Version eines Typs zum Bearbeiten (#13) — rohe Felder +
 * Beschreibung (NC-Forms-Editor). Beim frisch angelegten Typ ist `fields` leer.
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
 * Überblicks-Zeile aktiver Formulare (#75): Anzeigename, zuständiges Gremium,
 * Status und aktive Form-Version. Aggregiert aus Application-Type + Form-Version;
 * im Mock geseedet. TODO(T-24): aus `/admin/application-types` (+ Versionen)
 * ableiten, sobald der Endpunkt steht.
 */
export interface FormOverviewItem {
  id: Uuid;
  name: I18nMap;
  gremiumId?: Uuid | null;
  status: FormStatus;
  version: number;
}

// --- Notification-/Webhook-Config (config_schemas §5.4/§5.5) ----------------

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

/** Gremium-Rolle (#42) — eigener Rollensatz, getrennt von den globalen Rollen. */
export interface GremiumRole {
  id: Uuid;
  gremiumId: Uuid;
  key: string;
  name: I18nMap;
  /** Pflichtrolle (Vorstand/Manager/Mitglied) — vorhanden in jedem Gremium, nicht löschbar. */
  forced?: boolean;
  /** Granulare Sitzungs-Berechtigungen (session.manage/vote.manage/vote.cast/protocol.write). */
  permissions?: string[];
}

/** Konfigurierbare granulare Gremium-Rollen-Berechtigungen (#Sessions). */
export const GREMIUM_PERMISSIONS = [
  'session.manage',
  'vote.manage',
  'vote.cast',
  'protocol.write',
] as const;

/** Art einer benannten Frist-Policy. */
export type DeadlineKind = 'absolute' | 'relative_submitted' | 'relative_changed';

/** Benannte Frist-Policy (Registry, vom Flow per `key` referenziert). */
export interface DeadlinePolicy {
  id: Uuid;
  key: string;
  label: I18nMap;
  kind: DeadlineKind;
  /** Nur bei `absolute`: fixes Datum (pro Semester pflegbar), ISO-String. */
  absoluteAt?: string | null;
  /** Nur bei den relativen Varianten: Tage Versatz. */
  offsetDays?: number | null;
}

/** Zeitbegrenzte Gremium-Zugehörigkeit (#42, Amtszeit). */
export interface GremiumMembership {
  id: Uuid;
  principalId: Uuid;
  gremiumId: Uuid;
  gremiumRoleId: Uuid;
  validFrom: string | null;
  validUntil: string | null;
}

/** Append-only Audit-Eintrag (T-23, `GET /admin/audit`). */
export interface AuditEntry {
  id: number;
  at: string;
  actor: string | null;
  /** Klarname des Akteurs (vom Backend aufgelöst); null = System/unbekannt. */
  actorName: string | null;
  action: string;
  targetType: string | null;
  targetId: string | null;
  /** Menschenlesbares Ziel-Label (Antragstitel, Rollenname, …); null = unbekannt/gelöscht. */
  targetLabel?: string | null;
  data: Record<string, unknown>;
  /** UUID → Klarname für die in `data` eingebetteten Entity-Referenzen (vom Backend
   *  aufgelöst). Nur auflösbare Ids; sonst wird die rohe UUID gezeigt. */
  resolvedIds?: Record<string, string>;
  hash: string;
  prevHash: string | null;
}

/** Cursor-gepagte Audit-Antwort (Keyset auf `id`, neueste zuerst). */
export interface AuditPage {
  items: AuditEntry[];
  nextCursor: number | null;
  hasMore: boolean;
}

/** Distinkter Akteur für den Audit-Actor-Filter. */
export interface AuditActor {
  sub: string;
  name: string | null;
}

/** Plattform-Benachrichtigungs-Config (#task-reminder, P admin.notifications). */
export interface NotificationSettings {
  taskReminderEnabled: boolean;
  /** Tage ohne Statuswechsel, bis erinnert wird (≥ 1). */
  taskReminderAfterDays: number;
  /** Danach alle N Tage erneut; 0 = nur einmal je State-Aufenthalt. */
  taskReminderRepeatDays: number;
}

/** DSGVO-Löschantrag (Queue, P privacy.manage). */
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

/** Plattformweite DSGVO-Config (globaler Aufbewahrungs-Default, P privacy.manage). */
export interface PrivacySettings {
  defaultRetentionMonths: number;
}

// --- Branding / Site-Config (#21 — T-34-Contract, nicht SDS) ----------------

export type LogoSlot = 'wordmark' | 'imagemark' | 'favicon';

export interface BrandingAsset {
  /** Data-URL oder serverseitige Asset-URL der Bildmarke. */
  url: string;
  filename: string;
  mime: string;
  /** Größe in Bytes (für die mime/size-Hinweis-Anzeige). */
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
  /** Login-Hinweis, Landing/Welcome, Support, E-Mail-Footer — je i18n. */
  loginHint: I18nMap;
  welcome: I18nMap;
  support: I18nMap;
  emailFooter: I18nMap;
  /** Info-Text unter der Antrags-(Typ-)Auswahl (#18) — Markdown, je i18n. */
  applyInfo?: I18nMap;
}

export interface Branding {
  /** Voller App-Name (Browser-Tab, Kopfzeile, Startseite); leer ⇒ Default/i18n. */
  appName?: string;
  /** Kurzer App-Name (PWA-Symbol/Startbildschirm); leer ⇒ Default. */
  appShortName?: string;
  logos: Partial<Record<LogoSlot, BrandingAsset>>;
  footerColumns: FooterColumn[];
  copyright: I18nMap;
  legalLinks: FooterLink[];
  freetexts: SiteFreetexts;
}

/** Versionierte Site-Config: aktive Version + bearbeitbarer Entwurf (#21). */
export interface SiteConfig {
  version: number;
  active: Branding;
  draft: Branding;
  /** true, wenn `draft` ungespeicherte/unaktivierte Änderungen trägt. */
  hasDraftChanges: boolean;
}

/**
 * Akzeptierte Logo-MIME-Typen + Max-Größe (UI-Hinweis + Client-Guard).
 *
 * **Sicherheit — img-only-Kontrakt:** Branding-Logos werden als `branding`-JSON
 * site-weit persistiert und ausschließlich über `<img src>` gerendert (nie inline
 * ins DOM injiziert). `image/svg+xml` ist **bewusst ausgeschlossen** — ein SVG
 * kann `<script>`/`on*`-Handler tragen und wäre für einen künftigen Inline-SVG-
 * Consumer ein gespeicherter XSS-Vektor. Nur Raster-Formate (PNG/JPEG/WebP/ICO).
 * Wer Logos konsumiert, MUSS bei `<img src>` bleiben.
 */
export const LOGO_ACCEPT_MIME: readonly string[] = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/x-icon',
  'image/vnd.microsoft.icon',
] as const;
export const LOGO_MAX_SIZE_MB = 2;

/** Re-Export, damit Admin-Code nur aus `admin.models` importiert. */
export type { FormFieldDef };
