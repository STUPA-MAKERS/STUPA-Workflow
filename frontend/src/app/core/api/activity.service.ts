/**
 * API of the activity page (`/api/activity`, specs 001270-001277): the events of the
 * Anträge, To-Dos, Tickets and Sitzungen that the person made, holds or touched.
 *
 * The server reads the histories of the modules and asks the read rule of each module for
 * each item, so the client only binds the data. A step holds 50 events, newest first; the
 * next step starts at `nextCursor`. `readAt` of a step goes back as the new visit mark.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { IsoDateTime } from '@core/api/models';
import { skipLoading } from '@stupa-makers/ui-kit';
import { httpParams } from './http-params';

/** The kinds of item, in the order of the filter. */
export type ActivityItemKind = 'application' | 'todo' | 'ticket' | 'meeting';
export const ACTIVITY_KINDS: readonly ActivityItemKind[] = ['application', 'todo', 'ticket', 'meeting'];

/** `committee` stands for a member in the applicant view: the Gremium, never a name. */
export type ActivityActorKind = 'person' | 'system' | 'applicant' | 'committee';

export type ActivityChange =
  | 'application.status'
  | 'application.edited'
  | 'comment'
  | 'todo.created'
  | 'todo.moved'
  | 'todo.assigned'
  | 'todo.unassigned'
  | 'todo.due'
  | 'todo.linked'
  | 'todo.unlinked'
  | 'todo.checklist'
  | 'todo.renamed'
  | 'todo.archived'
  | 'todo.restored'
  | 'ticket.created'
  | 'ticket.status'
  | 'ticket.assignee'
  | 'ticket.kind'
  | 'ticket.todo_done'
  | 'meeting.status'
  | 'meeting.updated'
  | 'protocol.finalized'
  | 'protocol.approved'
  | 'protocol.reopened';

export interface ActivityActor {
  readonly kind: ActivityActorKind;
  /** The name of a `person`; `null` reads as "Ohne Namen". */
  readonly name?: string | null;
}

export interface ActivityEntry {
  readonly id: string;
  readonly at: IsoDateTime;
  readonly itemKind: ActivityItemKind;
  readonly itemId: string;
  readonly itemTitle: string | null;
  readonly url: string;
  readonly change: ActivityChange;
  /** The first line of a comment, a state, a column name. */
  readonly detail?: string | null;
  /** A status key of a ticket or a meeting. */
  readonly status?: string | null;
  readonly actor: ActivityActor;
  readonly own: boolean;
  readonly isNew: boolean;
}

export interface ActivityPage {
  readonly entries: readonly ActivityEntry[];
  readonly nextCursor: string | null;
  readonly seenAt: IsoDateTime | null;
  readonly readAt: IsoDateTime;
}

export interface ActivityQuery {
  readonly kinds?: readonly ActivityItemKind[];
  readonly own?: boolean;
  readonly cursor?: string | null;
  readonly lang?: string;
}

@Injectable({ providedIn: 'root' })
export class ActivityApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** One step of the page. */
  list(query: ActivityQuery = {}): Observable<ActivityPage> {
    const params = httpParams({
      kind: query.kinds?.length ? query.kinds : undefined,
      own: query.own ? true : undefined,
      cursor: query.cursor ?? undefined,
      lang: query.lang,
    });
    return this.http.get<ActivityPage>(`${this.base}/activity`, { params, context: skipLoading() });
  }

  /** Whether an event of another person waits after the last visit (the dot). */
  status(): Observable<{ readonly hasNew: boolean }> {
    return this.http.get<{ hasNew: boolean }>(`${this.base}/activity/status`, { context: skipLoading() });
  }

  /** Store `at` (the `readAt` of a step) as the last visit. */
  markSeen(at: IsoDateTime): Observable<void> {
    return this.http.post<void>(`${this.base}/activity/seen`, { at }, { context: skipLoading() });
  }
}
