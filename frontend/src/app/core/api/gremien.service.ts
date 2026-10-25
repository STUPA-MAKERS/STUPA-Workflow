/**
 * API of the tab "Gremien" (`/api/gremien`). Every call reads only.
 *
 * The server shows a gremium to an active member, to `gremium.view_all` and to the admin
 * role. Any other caller gets 404 for a gremium, so a hidden gremium looks like a missing
 * one. The client only binds the data; the server stays authoritative for RBAC.
 *
 * The excuse text of an attendance is in no answer, also not for the person: the tab
 * shows the status only.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { IsoDateTime, Uuid } from '@core/api/models';
import { detailContext } from '@core/cache/cache.interceptor';
import { skipLoading } from '@core/loading/loading.interceptor';

/** A text per locale, for example the name of a gremium role (`{ de, en }`). */
export type LocalizedText = Readonly<Record<string, string>>;

export type GremiumMeetingStatus = 'planned' | 'live' | 'closed';
export type GremiumProtocolStatus = 'draft' | 'rendering' | 'final';
/** The state of one member in one closed meeting. */
export type GremiumAttendanceState = 'present' | 'excused' | 'absent' | 'delegated';
/** `application`: a vote on an application; `motion`: a free motion; `election`. */
export type GremiumDecisionKind = 'application' | 'election' | 'motion';
/** `passed` includes an election with a winner; `rejected` includes a tie. */
export type GremiumDecisionResultFilter = 'passed' | 'rejected';

/** The live meeting of a gremium, else its next planned meeting. */
export interface GremiumNextMeeting {
  readonly id: Uuid;
  readonly title: string;
  /** `YYYY-MM-DD`, or null for a meeting without a date. */
  readonly date: string | null;
  /** `HH:MM:SS`. */
  readonly startTime: string | null;
  readonly status: GremiumMeetingStatus;
}

/** One row of `GET /gremien/overview`. */
export interface GremiumOverview {
  readonly id: Uuid;
  readonly name: string;
  readonly slug: string;
  /** The caller is an active member. */
  readonly isMember: boolean;
  readonly roleKey: string | null;
  readonly roleName: LocalizedText | null;
  readonly memberCount: number;
  readonly nextMeeting: GremiumNextMeeting | null;
  /** A meeting of the gremium runs now. */
  readonly live: boolean;
  readonly quorumPercent: number | null;
  readonly protocolsPublic: boolean;
  readonly allowVoteDelegation: boolean;
  /** The square logo of the CD variant (`/api/gremien/{id}/logo`), else null. */
  readonly logoUrl: string | null;
}

/** One membership (`GET /gremien/{id}/members`). */
export interface GremiumMember {
  readonly principalId: Uuid;
  readonly displayName: string | null;
  readonly email: string | null;
  readonly roleId: Uuid;
  readonly roleKey: string;
  readonly roleName: LocalizedText;
  readonly validFrom: IsoDateTime | null;
  readonly validUntil: IsoDateTime | null;
  readonly isSelf: boolean;
}

/** One meeting of a gremium (`GET /gremien/{id}/meetings`). */
export interface GremiumMeeting {
  readonly id: Uuid;
  readonly title: string;
  readonly date: string | null;
  readonly startTime: string | null;
  readonly endTime: string | null;
  readonly status: GremiumMeetingStatus;
  readonly agendaItemCount: number;
  readonly presentCount: number;
  /** The members of the meeting window, plus the people with a record. */
  readonly memberCount: number;
  readonly protocolStatus: GremiumProtocolStatus | null;
}

/** One month of the attendance range: `YYYY-MM` and the number of closed meetings. */
export interface GremiumAttendanceMonth {
  readonly month: string;
  readonly meetings: number;
}

/** The attendance of one person in one month. */
export interface GremiumAttendanceCell {
  readonly month: string;
  /** A membership overlaps the month. */
  readonly member: boolean;
  readonly present: number;
  readonly excused: number;
  /** Meetings in which the person transferred the vote. */
  readonly delegated: number;
}

/** One person of the attendance matrix. */
export interface GremiumAttendanceRow {
  readonly principalId: Uuid;
  readonly displayName: string | null;
  readonly roleKey: string | null;
  readonly roleName: LocalizedText | null;
  readonly isSelf: boolean;
  /** One cell per month of `months`, in the same order. */
  readonly cells: readonly GremiumAttendanceCell[];
}

/** `GET /gremien/{id}/attendance`: the matrix of a range of months. */
export interface GremiumAttendance {
  readonly fromMonth: string;
  readonly toMonth: string;
  readonly months: readonly GremiumAttendanceMonth[];
  readonly rows: readonly GremiumAttendanceRow[];
}

/** One closed meeting of a month with the state of one person. */
export interface GremiumMemberMeeting {
  readonly meetingId: Uuid;
  readonly title: string;
  readonly date: string | null;
  readonly startTime: string | null;
  readonly status: GremiumAttendanceState;
  /** The person who received the vote, for `delegated`. */
  readonly delegateName: string | null;
}

/** `GET /gremien/{id}/attendance/{principalId}?month=`. */
export interface GremiumMemberAttendance {
  readonly principalId: Uuid;
  readonly displayName: string | null;
  readonly month: string;
  readonly meetings: readonly GremiumMemberMeeting[];
}

/** The sums of a closed motion. A vote list never names a voter. */
export interface GremiumDecisionCounts {
  readonly yes: number;
  readonly no: number;
  readonly abstain: number;
}

/** One closed vote of a gremium. */
export interface GremiumDecision {
  readonly id: Uuid;
  readonly question: string | null;
  readonly kind: GremiumDecisionKind;
  readonly applicationId: Uuid | null;
  readonly applicationTitle: string | null;
  /** The requested amount of the application, as a decimal string ("2890.00"). */
  readonly amount: string | number | null;
  readonly secret: boolean;
  /** `simple`, `absolute` or `two_thirds`; null for an election. */
  readonly majorityRule: string | null;
  /** The sums of a motion; null for an election. */
  readonly counts: GremiumDecisionCounts | null;
  readonly ballots: number;
  /** `passed`, `rejected`, `tie`, `elected`, `runoff`, or null. */
  readonly result: string | null;
  /** The names of the elected candidates. */
  readonly elected: readonly string[];
  readonly meetingId: Uuid | null;
  readonly meetingTitle: string | null;
  readonly meetingDate: string | null;
  readonly closedAt: IsoDateTime | null;
}

/** One page of decisions, newest first. `nextCursor` is null on the last page. */
export interface GremiumDecisionPage {
  readonly items: readonly GremiumDecision[];
  readonly nextCursor: string | null;
}

/** The filters of `GET /gremien/{id}/decisions`. An empty value is no filter. */
export interface GremiumDecisionQuery {
  cursor?: string | null;
  q?: string | null;
  result?: GremiumDecisionResultFilter | null;
  kind?: GremiumDecisionKind | null;
  /** `YYYY-MM-DD`: only votes closed on this day or later. */
  since?: string | null;
}

/**
 * The API calls of the tab "Gremien". Every view of the tab has its own skeleton, so no call
 * shows the global overlay.
 */
@Injectable({ providedIn: 'root' })
export class GremienApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  overview(): Observable<GremiumOverview[]> {
    return this.http.get<GremiumOverview[]>(`${this.base}/gremien/overview`, {
      context: skipLoading(),
    });
  }

  members(gremiumId: Uuid, former = false): Observable<GremiumMember[]> {
    const params = former ? new HttpParams().set('former', 'true') : undefined;
    return this.http.get<GremiumMember[]>(`${this.base}/gremien/${gremiumId}/members`, {
      params,
      context: skipLoading(),
    });
  }

  /** Kept for the read ahead of the gremien list: the first tab of a gremium shows at once. */
  meetings(gremiumId: Uuid): Observable<GremiumMeeting[]> {
    return this.http.get<GremiumMeeting[]>(`${this.base}/gremien/${gremiumId}/meetings`, {
      context: detailContext(),
    });
  }

  /** The months `from` to `to` (`YYYY-MM`). Without them the server gives the last six. */
  attendance(gremiumId: Uuid, range: { from?: string; to?: string } = {}): Observable<GremiumAttendance> {
    let params = new HttpParams();
    if (range.from) params = params.set('from', range.from);
    if (range.to) params = params.set('to', range.to);
    return this.http.get<GremiumAttendance>(`${this.base}/gremien/${gremiumId}/attendance`, {
      params,
      context: skipLoading(),
    });
  }

  memberAttendance(
    gremiumId: Uuid,
    principalId: Uuid,
    month: string,
  ): Observable<GremiumMemberAttendance> {
    return this.http.get<GremiumMemberAttendance>(
      `${this.base}/gremien/${gremiumId}/attendance/${principalId}`,
      { params: new HttpParams().set('month', month), context: skipLoading() },
    );
  }

  decisions(gremiumId: Uuid, query: GremiumDecisionQuery = {}): Observable<GremiumDecisionPage> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(query)) {
      if (value) params = params.set(key, value);
    }
    return this.http.get<GremiumDecisionPage>(`${this.base}/gremien/${gremiumId}/decisions`, {
      params,
      context: skipLoading(),
    });
  }
}
