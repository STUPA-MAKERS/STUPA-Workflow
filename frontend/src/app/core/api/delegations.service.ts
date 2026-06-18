/**
 * Delegations-API (#delegation-rework) gegen `/api/delegations`.
 *
 * Eine Delegation ist **sitzungsgebunden**: angelegt mit `meetingId` + `delegateId`
 * (optional Stimmrecht), Gremium/Gültigkeit ergeben sich aus der Sitzung. Dazu der
 * Sitzungs-Kontext (Gates, Deadline, Empfänger), der Vote-Status (Banner in der
 * Stimmabgabe) und der pro Gremium gepflegte Stellvertreter-Pool. RBAC bleibt
 * serverseitig autoritativ — dieser Client ist reine Datenanbindung.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { skipLoading } from '@core/loading/loading.interceptor';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { IsoDateTime, Uuid } from '@core/api/models';

/** Sitzungsgebundene Vertretung (GET/POST /delegations). */
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
  /** Widerruf noch möglich (Sitzung `planned` + vor Beginn)? */
  readonly revocable: boolean;
  /** Richtung aus Sicht des Aufrufers; null = unbeteiligt (Admin-Sicht). */
  readonly direction: 'outgoing' | 'incoming' | null;
}

/** Body für POST /delegations. */
export interface DelegationInput {
  meetingId: Uuid;
  delegateId: Uuid;
  delegateVoting: boolean;
}

/** Wählbarer Empfänger (Typeahead-Quelle). */
export interface DelegationRecipient {
  readonly principalId: Uuid;
  readonly displayName: string | null;
  /** Stellvertreter-Pool → keine Vorlauf-Deadline. */
  readonly viaPool: boolean;
  readonly isMember: boolean;
}

/** Kontext des »Vertretung einrichten«-Dialogs (GET /delegations/meetings/{id}/context). */
export interface MeetingDelegationContext {
  readonly meetingId: Uuid;
  readonly gremiumId: Uuid;
  readonly allowVoteDelegation: boolean;
  readonly votingDelegationEnabled: boolean;
  readonly delegationAllowExternal: boolean;
  /** Deadline für Nicht-Pool-Delegationen (ISO/UTC); null = nur Status-Gate. */
  readonly deadline: IsoDateTime | null;
  readonly deadlinePassed: boolean;
  readonly meetingStarted: boolean;
  readonly canDelegate: boolean;
  readonly myDelegation: Delegation | null;
  readonly incoming: readonly Delegation[];
  readonly recipients: readonly DelegationRecipient[];
}

/** Delegations-Sicht auf eine Abstimmung (GET /delegations/votes/{id}/status). */
export interface VoteDelegationStatus {
  readonly blocked: boolean;
  readonly delegatedToName: string | null;
  readonly exercising: boolean;
  readonly delegatedByName: string | null;
}

/** Stellvertreter-Pool-Eintrag (GET/POST /delegations/substitutes). */
export interface DelegationSubstitute {
  readonly id: Uuid;
  readonly gremiumId: Uuid;
  /** null = gremium-weiter Stellvertreter (vertritt jedes Mitglied). */
  readonly memberId: Uuid | null;
  readonly memberName: string | null;
  readonly substituteId: Uuid;
  readonly substituteName: string | null;
}

/** Body für POST /delegations/substitutes. */
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
    // Liste hat einen eigenen Lade-Indikator (bzw. läuft im Dashboard im Hintergrund)
    // → globalen Overlay unterdrücken (#loading).
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

  /** `quiet` = Hintergrund-Reload nach Mutation (kein globaler Overlay). */
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
    // Debounced Typeahead → nie den globalen Overlay aufblitzen lassen (#loading).
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
