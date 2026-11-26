/**
 * API of the Veranstaltungen (`/api/events`, specs 003022-003034).
 *
 * An Event is an element of its own with a team. A member of the team reads and writes
 * it; for anybody else it does not exist (404). The money of an Event comes from its
 * links: the Anträge, the Buchungen and the invoices that a link joins to it. The client
 * only binds the data; the server stays authoritative.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { IsoDateTime, Uuid } from '@core/api/models';
import { skipLoading } from '@stupa-makers/ui-kit';
import { httpParams } from './http-params';

/** The key of a status of the list of the Events (`StatusCatalog`, spec 003035). */
export type EventStatus = string;

/** The money of an Event: decimal strings with two places; balance = income − expenses. */
export interface EventTotals {
  readonly requested: string;
  readonly approved: string;
  readonly expenses: string;
  readonly income: string;
  readonly balance: string;
}

/** One Event. Dates are `YYYY-MM-DD`, times `HH:MM:SS`. */
export interface EventItem {
  readonly id: Uuid;
  /** `V-` and eight characters. */
  readonly number: string;
  readonly teamId: Uuid;
  readonly teamName: string | null;
  readonly status: EventStatus;
  /** The phase of the status: `open`, `done` or `void`. */
  readonly phase: string;
  readonly title: string;
  readonly descriptionMd: string | null;
  readonly startsOn: string | null;
  readonly startTime: string | null;
  readonly endsOn: string | null;
  readonly endTime: string | null;
  readonly place: string | null;
  readonly participants: number | null;
  readonly seriesId: Uuid | null;
  readonly seriesName: string | null;
  readonly shopUrl: string | null;
  readonly totals: EventTotals;
  readonly version: number;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
}

/** A decision of an Event: the valid decision of a linked Antrag or a closed vote (000482). */
export interface EventDecision {
  readonly kind: 'decision' | 'vote';
  readonly targetId: Uuid | null;
  readonly title: string;
  readonly decidedAt: IsoDateTime | null;
  readonly meetingTitle: string | null;
  readonly result: string | null;
  readonly amount: string | null;
  readonly conditions: readonly string[];
}

/** Another Event of the series that the person reads (000483). */
export interface EventEdition {
  readonly id: Uuid;
  readonly number: string;
  readonly title: string;
  readonly status: EventStatus;
  readonly startsOn: string | null;
  readonly endsOn: string | null;
  readonly startTime: string | null;
  readonly endTime: string | null;
  readonly totals: EventTotals;
}

/** One Event with its decisions and the other Events of its series (003029). */
export interface EventDetail extends EventItem {
  readonly decisions: readonly EventDecision[];
  readonly editions: readonly EventEdition[];
  /** The Events of the series that the person does not read. */
  readonly hiddenEditions: number;
}

/** An open Event of a team of the person: an option of the picker of a Buchung. */
export interface EventRef {
  readonly id: Uuid;
  readonly number: string;
  readonly title: string;
  readonly teamName: string | null;
  readonly startsOn: string | null;
  readonly endsOn: string | null;
  readonly startTime: string | null;
  readonly endTime: string | null;
}

/** A team of the person, or a series (`Reihe`). */
export interface EventOption {
  readonly id: Uuid;
  readonly name: string;
}

/** The fields of a create or a change. A change sends only the fields it sets. */
export interface EventInput {
  readonly teamId?: Uuid;
  readonly title?: string;
  readonly status?: EventStatus;
  readonly descriptionMd?: string | null;
  readonly startsOn?: string | null;
  readonly startTime?: string | null;
  readonly endsOn?: string | null;
  readonly endTime?: string | null;
  readonly place?: string | null;
  readonly participants?: number | null;
  readonly seriesId?: Uuid | null;
  readonly shopUrl?: string | null;
}

/** The segments of the page "Veranstaltungen" (003028), in their order. */
export type EventSegment = 'upcoming' | 'past' | 'done' | 'void';
export const EVENT_SEGMENTS: readonly EventSegment[] = ['upcoming', 'past', 'done', 'void'];

/** The filter of the page. An empty value is no filter. */
export interface EventQuery {
  readonly segment?: EventSegment;
  readonly team?: string;
  readonly series?: string;
  readonly q?: string;
  readonly limit?: number;
  readonly offset?: number;
}

export interface EventPage {
  readonly items: readonly EventItem[];
  readonly total: number;
}

@Injectable({ providedIn: 'root' })
export class EventsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** The Events of the teams of the person. */
  page(query: EventQuery = {}): Observable<EventPage> {
    return this.http.get<EventPage>(`${this.base}/events`, {
      params: httpParams({ ...query }),
      context: skipLoading(),
    });
  }

  /** One Event with its decisions and editions; 404 for a person outside its team. */
  get(id: Uuid): Observable<EventDetail> {
    return this.http.get<EventDetail>(`${this.base}/events/${id}`, { context: skipLoading() });
  }

  /** The teams of the person: the field Team and the chip Team. */
  teams(): Observable<readonly EventOption[]> {
    return this.http.get<readonly EventOption[]>(`${this.base}/events/teams`, {
      context: skipLoading(),
    });
  }

  /** The open Events that the person writes: the picker of a Buchung (003033). */
  refs(q = ''): Observable<readonly EventRef[]> {
    return this.http.get<readonly EventRef[]>(`${this.base}/events/refs`, {
      params: httpParams({ q: q || undefined }),
      context: skipLoading(),
    });
  }

  /** The series by name, at most 50. */
  series(q = ''): Observable<readonly EventOption[]> {
    return this.http.get<readonly EventOption[]>(`${this.base}/events/series`, {
      params: httpParams({ q: q || undefined }),
      context: skipLoading(),
    });
  }

  /** 409 `series_exists` for a name that is taken, case ignored. */
  createSeries(name: string): Observable<EventOption> {
    return this.http.post<EventOption>(`${this.base}/events/series`, { name });
  }

  /** The Events of a filter as an XLSX file; needs `finance.export`. */
  exportXlsx(query: EventQuery = {}): Observable<Blob> {
    return this.http.get(`${this.base}/events/export.xlsx`, {
      params: httpParams({ ...query, limit: undefined, offset: undefined }),
      responseType: 'blob',
    });
  }

  /** 403 `event_team_forbidden`, 422 `event_url_invalid` and the date codes of 000736. */
  create(body: EventInput): Observable<EventDetail> {
    return this.http.post<EventDetail>(`${this.base}/events`, body);
  }

  /** 409 `event_version_conflict` when `version` is not the stored one. */
  update(id: Uuid, version: number, body: EventInput): Observable<EventDetail> {
    return this.http.patch<EventDetail>(`${this.base}/events/${id}`, { ...body, version });
  }

  setStatus(id: Uuid, status: EventStatus, version: number): Observable<EventDetail> {
    return this.http.post<EventDetail>(`${this.base}/events/${id}/status`, { status, version });
  }

  remove(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/events/${id}`);
  }
}
