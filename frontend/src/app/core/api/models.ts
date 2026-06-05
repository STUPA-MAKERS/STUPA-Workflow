/**
 * API-DTOs — abgeleitet aus den OpenAPI-Contracts (sds/api.md §2/§5).
 * Single Source of Truth bleibt das Backend-OpenAPI; diese Typen sind die
 * FE-seitige Spiegelung für den typisierten API-Client. Bei Contract-Änderung
 * → abstimmen (tasks.md §Konventionen), nicht einseitig brechen.
 */

export type Uuid = string;
export type IsoDateTime = string;
export type Lang = 'de' | 'en';

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

/** Principal (OIDC) inkl. Rollen/Permissions/Gruppen — GET /api/auth/me. */
export interface Principal {
  id: Uuid;
  displayName: string;
  email: string;
  roles: string[];
  permissions: string[];
  groups: Uuid[];
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
