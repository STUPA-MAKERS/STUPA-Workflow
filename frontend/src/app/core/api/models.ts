/**
 * API-DTOs — abgeleitet aus den OpenAPI-Contracts (sds/api.md §2/§5).
 * Single Source of Truth bleibt das Backend-OpenAPI; diese Typen sind die
 * FE-seitige Spiegelung für den typisierten API-Client. Bei Contract-Änderung
 * → abstimmen (tasks.md §Konventionen), nicht einseitig brechen.
 */

export type Uuid = string;
export type IsoDateTime = string;
export type Lang = 'de' | 'en';

/** Konfigurierbarer mehrsprachiger Text (`*_i18n`-JSONB, overview §5). */
export type I18nMap = Record<string, string>;

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
 * Feldnamen spiegeln das Backend-`MeOut` (auth/schemas.py) 1:1; das OpenAPI
 * bleibt Single Source of Truth — hier nicht einseitig umbenennen.
 */
export interface Principal {
  sub: Uuid;
  email?: string | null;
  display_name?: string | null;
  roles: string[];
  permissions: string[];
  groups: string[];
}

/** Antwort von POST /api/auth/logout — RP-Initiated-Logout-URL (OIDC) oder null. */
export interface LogoutOut {
  logout_url: string | null;
}

export interface StateOut {
  key: string;
  label: string;
  editAllowed: boolean;
}

export interface ApplicationType {
  id: Uuid;
  name: string;
  active: boolean;
}

export interface ApplicationCreate {
  type_id: Uuid;
  budget_pot_id?: Uuid | null;
  data: Record<string, unknown>;
  applicant_email: string;
  applicant_name?: string | null;
  lang: Lang;
  altcha: string;
}

export interface ApplicationOut {
  id: Uuid;
  type_id: Uuid;
  state: StateOut;
  gremium_id: Uuid | null;
  budget_pot_id: Uuid | null;
  amount: string | null;
  data: Record<string, unknown>;
  version: number;
  created_at: IsoDateTime;
}

export interface TimelineEntry {
  state: string;
  label: string;
  at: IsoDateTime;
  note?: string;
}

export interface Transition {
  id: Uuid;
  label: string;
  toState: string;
}

export interface TransitionRequest {
  transition_id: Uuid;
  note?: string | null;
}

export type MajorityRule = 'simple' | 'absolute' | 'two_thirds';

export interface VoteConfig {
  options: string[];
  majority_rule: MajorityRule;
  abstain_counts_quorum: boolean;
  secret: boolean;
  allow_change: boolean;
  tie_break: 'passed' | 'rejected' | 'tie';
}

export interface TallyOut {
  counts: Record<string, number>;
  eligible: number;
  quorum_met: boolean;
  leading: string | null;
  result: string | null;
}

export interface AttachmentOut {
  id: Uuid;
  filename: string;
  mime: string;
  size: number;
  scanned: boolean;
  is_comparison_offer: boolean;
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
  q?: string;
  limit?: number;
  offset?: number;
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
  | 'computed';

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
  isPII?: boolean;
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

// --- Magic-Link + Kommentare (api.md §1/§3) -----------------------------------

/**
 * Antwort von POST /api/auth/magic-link/verify (`MagicLinkVerifyOut`,
 * auth/schemas.py — T-10). Die Applicant-Session läuft **ausschließlich** über
 * eine HttpOnly-Cookie (security.md §1) — **kein** Session-Token im Body/JS.
 */
export interface MagicLinkVerifyResult {
  application_id: Uuid;
  scope: 'edit' | 'view';
}

/**
 * Öffentlicher Kommentar (api.md §3 applications/comments). snake_case wie die
 * übrigen Application-DTOs; das Backend-Schema kommt mit T-12 (PR #13) — vor
 * T-40 gegen das dann exportierte OpenAPI abgleichen.
 */
export interface ApplicationComment {
  id: Uuid;
  body: string;
  author_name?: string | null;
  created_at: IsoDateTime;
  is_public: boolean;
}
