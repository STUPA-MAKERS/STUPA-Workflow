/**
 * API of the Kalender (`/api/calendar`): the entries of the page, the search, and the
 * Termine with their invitations and answers.
 *
 * The server reads each kind of entry under the rule of its own module, and a Termin
 * that the caller does not read answers 404. The client only binds the data.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, map } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';
import { skipLoading } from '@stupa-makers/ui-kit';
import { httpParams } from './http-params';

/** The kinds of entries on the wire. The page counts an Event to the Termine. */
export type EntryKind = 'meeting' | 'card' | 'event' | 'appointment';

/** The answers of an invited person, in the order of the answer control. */
export type AnswerKey = 'accept' | 'tentative' | 'decline';
export const ANSWER_KEYS: readonly AnswerKey[] = ['accept', 'tentative', 'decline'];

/** One entry of the Kalender. A time is `HH:MM:SS`, and null for an all-day entry. */
export interface CalendarEntry {
  readonly kind: EntryKind;
  readonly id: Uuid;
  readonly title: string;
  readonly startsOn: string;
  readonly endsOn: string;
  readonly startTime: string | null;
  readonly endTime: string | null;
  readonly place: string | null;
  /** The Gremium of a meeting, the board of a card, the first invited Gremium of a Termin. */
  readonly source: string | null;
  readonly gremiumIds: readonly Uuid[];
  /** A card assigned to the caller, a Termin that the caller created or is invited to. */
  readonly mine: boolean;
  readonly myAnswer: AnswerKey | null;
}

export interface CalendarPerson {
  readonly id: Uuid;
  readonly name: string;
}

export interface CalendarGremium {
  readonly id: Uuid;
  readonly name: string;
}

export interface AppointmentAnswer {
  readonly principalId: Uuid;
  readonly name: string;
  readonly answer: AnswerKey;
}

/** A Termin as its reader sees it. `answers` is empty for a reader who is not invited. */
export interface Appointment {
  readonly id: Uuid;
  readonly title: string;
  readonly startsOn: string;
  readonly endsOn: string;
  readonly startTime: string | null;
  readonly endTime: string | null;
  readonly place: string | null;
  readonly description: string | null;
  readonly forAll: boolean;
  readonly creator: CalendarPerson | null;
  readonly gremien: readonly CalendarGremium[];
  readonly persons: readonly CalendarPerson[];
  readonly answers: readonly AppointmentAnswer[];
  readonly myAnswer: AnswerKey | null;
  readonly invited: boolean;
  readonly canEdit: boolean;
}

/** The whole data of a Termin, for the create and for the change. */
export interface AppointmentInput {
  readonly title: string;
  readonly startsOn: string;
  readonly endsOn: string;
  readonly startTime: string | null;
  readonly endTime: string | null;
  readonly place: string | null;
  readonly description: string | null;
  readonly forAll: boolean;
  readonly gremiumIds: readonly Uuid[];
  readonly principalIds: readonly Uuid[];
}

@Injectable({ providedIn: 'root' })
export class CalendarApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${inject(API_BASE_URL)}/calendar`;

  /** The entries with a day between `from` and `to` (both included, at most 100 days). */
  entries(from: string, to: string, mine: boolean): Observable<readonly CalendarEntry[]> {
    return this.http
      .get<{ items: readonly CalendarEntry[] }>(`${this.base}/entries`, {
        params: httpParams({ from, to, mine: mine || undefined }),
        context: skipLoading(),
      })
      .pipe(map((page) => page.items));
  }

  /** The entries of every month whose title holds `q`, the nearest to today first. */
  search(q: string): Observable<readonly CalendarEntry[]> {
    return this.http
      .get<{ items: readonly CalendarEntry[] }>(`${this.base}/search`, {
        params: httpParams({ q }),
        context: skipLoading(),
      })
      .pipe(map((page) => page.items));
  }

  /** The active accounts whose name holds `q` (two characters or more). */
  people(q: string): Observable<readonly CalendarPerson[]> {
    return this.http.get<readonly CalendarPerson[]>(`${this.base}/people`, {
      params: httpParams({ q }),
      context: skipLoading(),
    });
  }

  appointment(id: Uuid): Observable<Appointment> {
    return this.http.get<Appointment>(`${this.base}/appointments/${id}`);
  }

  create(body: AppointmentInput): Observable<Appointment> {
    return this.http.post<Appointment>(`${this.base}/appointments`, body);
  }

  update(id: Uuid, body: AppointmentInput): Observable<Appointment> {
    return this.http.put<Appointment>(`${this.base}/appointments/${id}`, body);
  }

  remove(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/appointments/${id}`);
  }

  answer(id: Uuid, answer: AnswerKey): Observable<Appointment> {
    return this.http.put<Appointment>(`${this.base}/appointments/${id}/answer`, { answer });
  }
}
