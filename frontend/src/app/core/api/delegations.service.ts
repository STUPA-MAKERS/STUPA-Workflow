/**
 * Delegations API for `/api/delegations`.
 *
 * A delegation is session-bound. The caller creates it with `meetingId` and
 * `delegateId` plus an optional voting right. The Gremium and the validity come
 * from the meeting. The service also serves the meeting context (gates,
 * deadline, recipients), the vote status for the ballot banner and the
 * per-Gremium substitute pool. The server stays authoritative for RBAC. This
 * client only binds data.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { skipLoading } from '@core/loading/loading.interceptor';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { IsoDateTime, Uuid } from '@core/api/models';

/** Session-bound delegation (GET/POST /delegations). */
export interface Delegation {
  readonly id: Uuid;
  readonly meetingId: Uuid;
  readonly meetingTitle: string | null;
  readonly meetingDate: string | null;
  readonly gremiumId: Uuid;
  readonly gremiumName: string | null;
  readonly delegatorId: Uuid;
  readonly delegatorName: string | null;
  readonly delegateId: Uuid;
  readonly delegateName: string | null;
  readonly delegateVoting: boolean;
  readonly viaPool: boolean;
  readonly createdAt: IsoDateTime;
  /** True while revocation is possible: meeting `planned` and before the start. */
  readonly revocable: boolean;
  /** Direction from the view of the caller. `null` = not involved (admin view). */
  readonly direction: 'outgoing' | 'incoming' | null;
}

/** Body for POST /delegations. */
export interface DelegationInput {
  meetingId: Uuid;
  delegateId: Uuid;
  delegateVoting: boolean;
}

/** Selectable recipient (typeahead source). */
export interface DelegationRecipient {
  readonly principalId: Uuid;
  readonly displayName: string | null;
  /** Substitute pool → no lead-time deadline. */
  readonly viaPool: boolean;
  readonly isMember: boolean;
}

/** Context of the "create delegation" dialog (GET /delegations/meetings/{id}/context). */
export interface MeetingDelegationContext {
  readonly meetingId: Uuid;
  readonly gremiumId: Uuid;
  readonly allowVoteDelegation: boolean;
  readonly votingDelegationEnabled: boolean;
  readonly delegationAllowExternal: boolean;
  /** Deadline for non-pool delegations (ISO/UTC). `null` = status gate only. */
  readonly deadline: IsoDateTime | null;
  readonly deadlinePassed: boolean;
  readonly meetingStarted: boolean;
  readonly canDelegate: boolean;
  readonly myDelegation: Delegation | null;
  readonly incoming: readonly Delegation[];
  readonly recipients: readonly DelegationRecipient[];
}

/** Delegation view of a vote (GET /delegations/votes/{id}/status). */
export interface VoteDelegationStatus {
  readonly blocked: boolean;
  readonly delegatedToName: string | null;
  readonly exercising: boolean;
  readonly delegatedByName: string | null;
}

/** Substitute-pool entry (GET/POST /delegations/substitutes). */
export interface DelegationSubstitute {
  readonly id: Uuid;
  readonly gremiumId: Uuid;
  /** `null` = Gremium-wide substitute that represents every member. */
  readonly memberId: Uuid | null;
  readonly memberName: string | null;
  readonly substituteId: Uuid;
  readonly substituteName: string | null;
}

/** Body for POST /delegations/substitutes. */
export interface SubstituteInput {
  gremiumId: Uuid;
  memberId?: Uuid | null;
  substituteId: Uuid;
}

@Injectable({ providedIn: 'root' })
export class DelegationsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  list(meetingId?: Uuid): Observable<Delegation[]> {
    const params = meetingId ? new HttpParams().set('meetingId', meetingId) : undefined;
    // The list has its own loading indicator, or it runs in the background on
    // the dashboard → suppress the global overlay.
    return this.http.get<Delegation[]>(`${this.base}/delegations`, {
      params,
      context: skipLoading(),
    });
  }

  create(input: DelegationInput): Observable<Delegation> {
    return this.http.post<Delegation>(`${this.base}/delegations`, input);
  }

  revoke(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/delegations/${id}`);
  }

  /** `quiet` skips the global overlay for a background reload after a mutation. */
  meetingContext(
    meetingId: Uuid,
    opts: { quiet?: boolean } = {},
  ): Observable<MeetingDelegationContext> {
    return this.http.get<MeetingDelegationContext>(
      `${this.base}/delegations/meetings/${meetingId}/context`,
      { context: opts.quiet ? skipLoading() : undefined },
    );
  }

  recipients(meetingId: Uuid, q: string): Observable<DelegationRecipient[]> {
    // Debounced typeahead → never flash the global overlay.
    return this.http.get<DelegationRecipient[]>(
      `${this.base}/delegations/meetings/${meetingId}/recipients`,
      { params: new HttpParams().set('q', q), context: skipLoading() },
    );
  }

  voteStatus(voteId: Uuid): Observable<VoteDelegationStatus> {
    return this.http.get<VoteDelegationStatus>(`${this.base}/delegations/votes/${voteId}/status`);
  }

  substitutes(gremiumId: Uuid): Observable<DelegationSubstitute[]> {
    return this.http.get<DelegationSubstitute[]>(`${this.base}/delegations/substitutes`, {
      params: new HttpParams().set('gremiumId', gremiumId),
    });
  }

  addSubstitute(input: SubstituteInput): Observable<DelegationSubstitute> {
    return this.http.post<DelegationSubstitute>(`${this.base}/delegations/substitutes`, input);
  }

  removeSubstitute(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/delegations/substitutes/${id}`);
  }
}
