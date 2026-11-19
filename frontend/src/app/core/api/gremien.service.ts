/**
 * API of the tab "Gremien" (`/api/committees`). Every call reads, except `saveInfo`, the
 * save of the Info tab (gremium permission `info.write`).
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
import { skipLoading } from '@stupa-makers/ui-kit';
import { httpParams } from './http-params';

/** A text per locale, for example the name of a gremium role (`{ de, en }`). */
export type LocalizedText = Readonly<Record<string, string>>;

export type GremiumMeetingStatus = 'planned' | 'live' | 'closed';
export type GremiumProtocolStatus = 'draft' | 'rendering' | 'final';
/**
 * The state of one person in one closed meeting. `seat` and `noSeat` are the states of a
 * pool substitute (§ 001310): a pool seat taken, or none.
 */
export type GremiumAttendanceState =
  | 'present'
  | 'excused'
  | 'absent'
  | 'delegated'
  | 'seat'
  | 'no_seat';
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

/** One row of `GET /committees/overview`. */
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
  /** The least number of present persons for the quorum of a meeting vote. */
  readonly quorumMinPresent?: number | null;
  readonly protocolsPublic: boolean;
  readonly allowVoteDelegation: boolean;
  /** The square logo of the CD variant (`/api/committees/{id}/logo`), else null. */
  readonly logoUrl: string | null;
}

/** One membership (`GET /committees/{id}/members`). */
export interface GremiumMember {
  readonly principalId: Uuid;
  readonly displayName: string | null;
  readonly email: string | null;
  readonly roleId: Uuid;
  readonly roleKey: string;
  readonly roleName: LocalizedText;
  readonly isSelf: boolean;
}

/** One meeting of a gremium (`GET /committees/{id}/meetings`). */
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
  /** The final protocol has the mark "genehmigt" (§ 000924). */
  readonly protocolApproved?: boolean;
}

/** One month of the attendance range: `YYYY-MM` and the number of closed meetings. */
export interface GremiumAttendanceMonth {
  readonly month: string;
  readonly meetings: number;
}

/** The attendance of one person in one month. */
export interface GremiumAttendanceCell {
  readonly month: string;
  /** A membership overlaps the month; always true in a pool row. */
  readonly member: boolean;
  /** Present meetings; in a pool row the pool seats. */
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
  /** The unexcused absences of the chosen term (§ 000920, § 000941). */
  readonly unexcused: number;
  /** One cell per month of `months`, in the same order. */
  readonly cells: readonly GremiumAttendanceCell[];
  /** The row of a pool substitute: the cells count pool seats (§ 001310). */
  readonly pool?: boolean;
}

/** `GET /committees/{id}/attendance`: the matrix of a range of months. */
export interface GremiumAttendance {
  readonly fromMonth: string;
  readonly toMonth: string;
  /** The first day of the chosen term (`YYYY-MM-DD`). `unexcused` counts from it. */
  readonly termStart: string;
  /** The first day of each term on offer, the newest first; the first one is the current term. */
  readonly terms: readonly string[];
  /** The number of unexcused absences in one term that ends a Mandat. */
  readonly absenceLimit: number;
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
  /** The person who received the vote, for `delegated`; the represented member, for `seat`. */
  readonly delegateName: string | null;
  /** The end of the late-excuse window, only on an own `absent` row while it is open (§ 000922). */
  readonly lateExcuseUntil?: string | null;
}

/** `GET /committees/{id}/attendance/{principalId}?month=`. */
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
  /** One of the five majority rules (`MajorityRule`); null for an election. */
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

/** The filters of `GET /committees/{id}/decisions`. An empty value is no filter. */
export interface GremiumDecisionQuery {
  readonly cursor?: string | null;
  readonly q?: string | null;
  readonly result?: GremiumDecisionResultFilter | null;
  readonly kind?: GremiumDecisionKind | null;
  /** `YYYY-MM-DD`: only votes closed on this day or later. */
  readonly since?: string | null;
}

/** One labelled link of the Info tab: a label and an `https`, `http` or `mailto` URL. */
export interface GremiumInfoLink {
  readonly label: string;
  readonly url: string;
}

/** The Info tab of a gremium (specs 001010-001015). An unsaved Info has version 0. */
export interface GremiumInfo {
  readonly bodyMd: string;
  readonly links: readonly GremiumInfoLink[];
  readonly version: number;
  readonly updatedAt: IsoDateTime | null;
  readonly updatedByName: string | null;
  /** The caller holds `info.write` in the gremium. */
  readonly canEdit: boolean;
}

/** A save of the Info tab: text and links together, with the version that was read. */
export interface GremiumInfoSave {
  readonly bodyMd: string;
  readonly links: readonly GremiumInfoLink[];
  readonly version: number;
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
    return this.http.get<GremiumOverview[]>(`${this.base}/committees/overview`, {
      context: skipLoading(),
    });
  }

  members(gremiumId: Uuid, former = false): Observable<GremiumMember[]> {
    const params = former ? new HttpParams().set('former', 'true') : undefined;
    return this.http.get<GremiumMember[]>(`${this.base}/committees/${gremiumId}/members`, {
      params,
      context: skipLoading(),
    });
  }

  /** Kept for the read ahead of the gremien list: the first tab of a gremium shows at once. */
  meetings(gremiumId: Uuid): Observable<GremiumMeeting[]> {
    return this.http.get<GremiumMeeting[]>(`${this.base}/committees/${gremiumId}/meetings`, {
      context: detailContext(),
    });
  }

  /**
   * The months `from` to `to` (`YYYY-MM`). Without them the server gives the last six.
   * `term` is a day (`YYYY-MM-DD`) of the term that `unexcused` counts; with it and
   * without a range the server gives the months of this term (§ 000941).
   */
  attendance(
    gremiumId: Uuid,
    range: { from?: string; to?: string; term?: string } = {},
  ): Observable<GremiumAttendance> {
    const params = httpParams({
      from: range.from || undefined,
      to: range.to || undefined,
      term: range.term || undefined,
    });
    return this.http.get<GremiumAttendance>(`${this.base}/committees/${gremiumId}/attendance`, {
      params,
      context: skipLoading(),
    });
  }

  /**
   * GET /committees/{id}/attendance/export.xlsx — one row per person with the number of
   * closed ordinary meetings with `present`, for the days `from` to `to` (`YYYY-MM-DD`).
   * Needs `session.manage` in the Gremium (§ 000923).
   */
  attendanceExport(gremiumId: Uuid, from: string, to: string): Observable<Blob> {
    return this.http.get(`${this.base}/committees/${gremiumId}/attendance/export.xlsx`, {
      params: new HttpParams().set('from', from).set('to', to),
      responseType: 'blob',
    });
  }

  /** `pool`: read the person as a pool substitute (states `seat` and `no_seat`). */
  memberAttendance(
    gremiumId: Uuid,
    principalId: Uuid,
    month: string,
    pool = false,
  ): Observable<GremiumMemberAttendance> {
    const params = new HttpParams().set('month', month);
    return this.http.get<GremiumMemberAttendance>(
      `${this.base}/committees/${gremiumId}/attendance/${principalId}`,
      { params: pool ? params.set('pool', 'true') : params, context: skipLoading() },
    );
  }

  decisions(gremiumId: Uuid, query: GremiumDecisionQuery = {}): Observable<GremiumDecisionPage> {
    const params = httpParams(
      Object.fromEntries(Object.entries(query).map(([key, value]) => [key, value || undefined])),
    );
    return this.http.get<GremiumDecisionPage>(`${this.base}/committees/${gremiumId}/decisions`, {
      params,
      context: skipLoading(),
    });
  }

  /** The Info tab of a gremium: the Markdown text, the links and `canEdit`. */
  info(gremiumId: Uuid): Observable<GremiumInfo> {
    return this.http.get<GremiumInfo>(`${this.base}/committees/${gremiumId}/info`, {
      context: skipLoading(),
    });
  }

  /** Save text and links; a stale `version` gives 409 `gremium_info_version_conflict`. */
  saveInfo(gremiumId: Uuid, body: GremiumInfoSave): Observable<GremiumInfo> {
    return this.http.put<GremiumInfo>(`${this.base}/committees/${gremiumId}/info`, body);
  }
}
