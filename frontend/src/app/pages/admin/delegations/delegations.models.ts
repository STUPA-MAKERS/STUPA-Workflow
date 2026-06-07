import type { Uuid } from '@core/api/models';

/**
 * Delegation/Vertretung (T-45, R1.5) — FE-Sicht auf `/api/delegations`.
 * Eine Delegation überträgt eine selbst gehaltene Rolle (optional inkl. Stimmrecht)
 * zeitlich begrenzt an ein anderes Mitglied.
 */
export interface Delegation {
  readonly id: Uuid;
  readonly principalId: Uuid;
  readonly roleId: Uuid;
  readonly gremiumId: Uuid | null;
  readonly delegatedBy: string | null;
  readonly grantedBy: string | null;
  readonly validFrom: string | null;
  readonly validUntil: string | null;
  readonly delegateVoting: boolean;
  readonly active: boolean;
}

/** Eingabe zum Anlegen einer Delegation (camelCase = Backend-Kontrakt). */
export interface DelegationInput {
  principalId: Uuid;
  roleId: Uuid;
  gremiumId?: Uuid | null;
  validFrom?: string | null;
  validUntil: string;
  delegateVoting: boolean;
}
