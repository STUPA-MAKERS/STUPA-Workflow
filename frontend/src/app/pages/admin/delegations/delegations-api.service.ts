/**
 * Delegations-API-Client (T-45) gegen `/api/delegations`.
 *
 * Im Mock-Modus (`USE_MOCK_API`, Default true bis das Backend deployt ist) bedient
 * ein In-Memory-Store die UI; im Real-Modus gehen die exakten REST-Calls raus
 * (GET Liste, POST Anlegen, DELETE Widerruf). Beim Backend-Rollout nur
 * `USE_MOCK_API` auf false — die Real-Pfade sind verdrahtet.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, of } from 'rxjs';
import { API_BASE_URL, USE_MOCK_API } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';
import type { Delegation, DelegationInput } from './delegations.models';

@Injectable({ providedIn: 'root' })
export class DelegationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly mock = inject(USE_MOCK_API);

  // In-Memory-Store (nur Mock-Modus). Pro Service-Instanz, reicht für UI/Tests.
  private store: Delegation[] = [];
  private seq = 0;

  list(): Observable<Delegation[]> {
    if (this.mock) return of(structuredCopy(this.store));
    return this.http.get<Delegation[]>(`${this.base}/delegations`);
  }

  create(input: DelegationInput): Observable<Delegation> {
    if (this.mock) {
      const created: Delegation = {
        id: `del-${++this.seq}`,
        principalId: input.principalId,
        roleId: input.roleId,
        gremiumId: input.gremiumId ?? null,
        delegatedBy: 'me',
        grantedBy: 'me',
        validFrom: input.validFrom ?? null,
        validUntil: input.validUntil,
        delegateVoting: input.delegateVoting,
        active: true,
      };
      this.store = [...this.store, created];
      return of(structuredCopy(created));
    }
    return this.http.post<Delegation>(`${this.base}/delegations`, input);
  }

  revoke(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store = this.store.filter((d) => d.id !== id);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/delegations/${id}`);
  }
}

/** Deep-Copy ohne `structuredClone`-Verfügbarkeitsannahme (jsdom-sicher). */
function structuredCopy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
