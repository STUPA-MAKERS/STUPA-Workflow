/**
 * API of the tickets (`/api/tickets`): the "Problem melden" dialog sends a ticket, and
 * the page `/tickets` (permission `ticket.manage`) reads and works them.
 *
 * A reporter account reads its own tickets under `/tickets/mine`: the report, the
 * public notes and the status changes, and it writes, edits and deletes its own
 * messages. Every other read and write below the create needs `ticket.manage`; an
 * unknown ticket and a ticket the caller may not read both answer 404. The client only
 * binds the data; the server stays authoritative.
 */
import { type HttpContext, HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { IsoDateTime, MessageAttachment, MessageFiles, PersonRef, ScanState, Uuid } from '@core/api/models';
import { messageFiles } from '@core/api/mappers';
import { skipLoading } from '@stupa-makers/ui-kit';
import { detailContext } from '@core/cache/cache.interceptor';
import { httpParams } from './http-params';

export type TicketKind = 'bug' | 'question' | 'idea' | 'barrier';
export type TicketStatus = 'new' | 'in_progress' | 'done' | 'rejected';

/** The kinds in the order of the dialog and the filter. */
export const TICKET_KINDS: readonly TicketKind[] = ['bug', 'question', 'idea', 'barrier'];

/** What the dialog sends along: every field optional, capped by the server. */
export interface TicketContext {
  readonly url?: string;
  readonly route?: string;
  readonly appVersion?: string;
  readonly userAgent?: string;
  readonly viewport?: string;
  readonly language?: string;
  readonly colorScheme?: 'light' | 'dark';
}

export interface TicketCreate {
  readonly kind: TicketKind;
  readonly title: string;
  readonly body: string;
  /** Required without a session; the server ignores it with one. */
  readonly email?: string | null;
  readonly context: TicketContext;
  readonly attachmentIds?: readonly Uuid[];
  readonly draftToken?: string | null;
  /** Required without a session. */
  readonly altcha?: string | null;
}

/** The only answer to the reporter: the number, for example "T-0042". */
export interface TicketCreated {
  readonly number: string;
}

export interface TicketReporter {
  readonly principalId: Uuid | null;
  readonly displayName: string | null;
  /** The account e-mail or the given e-mail; null after the anonymization. */
  readonly email: string | null;
  readonly anonymized: boolean;
}

export interface TicketListItem {
  readonly id: Uuid;
  readonly number: string;
  readonly kind: TicketKind;
  readonly title: string;
  readonly status: TicketStatus;
  readonly reporter: TicketReporter;
  readonly assignee: PersonRef | null;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
}

/** A file of the report. Only a `clean` file downloads, streamed through the API. */
export interface TicketAttachment {
  readonly id: Uuid;
  readonly filename: string;
  readonly mime: string;
  readonly size: number;
  /** The scan ended; it does not say whether it found anything. */
  readonly scanned: boolean;
  /** The three-state scan of the server, as on a message file. */
  readonly scanState?: ScanState;
}

export type TicketEventKind = 'created' | 'status' | 'assignee' | 'kind' | 'todo_done';

/** The payloads of the event kinds, all optional so one type reads every kind. */
export interface TicketEventPayload {
  /** created */
  readonly confirmationSent?: boolean;
  /** status, assignee, kind */
  readonly from?: TicketStatus | TicketKind | PersonRef | null;
  readonly to?: TicketStatus | TicketKind | PersonRef | null;
  /** status: the number of the ticket this one duplicates. */
  readonly duplicateOf?: string;
  /** todo_done */
  readonly cardId?: Uuid;
  readonly cardTitle?: string | null;
  readonly boardId?: Uuid;
}

export interface TicketEvent {
  readonly id: Uuid;
  readonly kind: TicketEventKind;
  /** null: the system. */
  readonly actor: PersonRef | null;
  readonly at: IsoDateTime;
  readonly payload: TicketEventPayload;
}

/** `internal`: the holders of `ticket.manage` only; `public`: the reporter account too. */
export type TicketNoteVisibility = 'internal' | 'public';

export interface TicketNote {
  readonly id: Uuid;
  readonly author: PersonRef;
  readonly body: string;
  readonly at: IsoDateTime;
  readonly editedAt: IsoDateTime | null;
  readonly isOwn: boolean;
  /** The files of the note, oldest first. */
  readonly attachments: readonly MessageAttachment[];
  /** Absent on an older server: internal. */
  readonly visibility?: TicketNoteVisibility;
  /** The reporter wrote it. */
  readonly fromReporter?: boolean;
  /** The people the note mentions; empty for the reporter. */
  readonly mentions?: readonly PersonRef[];
}

export interface TicketDetail extends TicketListItem {
  readonly body: string;
  readonly context: TicketContext;
  readonly attachments: readonly TicketAttachment[];
  readonly notes: readonly TicketNote[];
  readonly events: readonly TicketEvent[];
  readonly duplicateOf: { readonly id: Uuid; readonly number: string } | null;
  /** The application or meeting of `context.route`, when the viewer may read it. */
  readonly contextTarget: {
    readonly kind: 'application' | 'meeting';
    readonly id: Uuid;
    readonly title: string;
  } | null;
  /** Linked cards that are open and readable. */
  readonly openTodoCount: number;
  readonly closedAt: IsoDateTime | null;
  readonly anonymizedAt: IsoDateTime | null;
  /** The reporter is blocked; false for an anonymized ticket. */
  readonly senderBlocked: boolean;
}

/**
 * A blocked sender of "Absender sperren". A report of a blocked sender gets a number,
 * but nothing is stored and no mail goes out.
 */
export interface TicketBlockedSender {
  readonly id: Uuid;
  readonly kind: 'principal' | 'email';
  /** kind `principal`. */
  readonly person: PersonRef | null;
  /** kind `email`: the stored address; kind `principal`: the account e-mail. */
  readonly email: string | null;
  /** null: a deleted person. */
  readonly blockedBy: PersonRef | null;
  readonly blockedAt: IsoDateTime;
  /** null after the ticket is gone. */
  readonly sourceTicket: { readonly id: Uuid; readonly number: string } | null;
  /** Reports held back since the block. */
  readonly hitCount: number;
  readonly lastHitAt: IsoDateTime | null;
}

/** A ticket in the list of its reporter: no reporter, no assignee. */
export interface MyTicketItem {
  readonly id: Uuid;
  readonly number: string;
  readonly kind: TicketKind;
  readonly title: string;
  readonly status: TicketStatus;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
}

/** The own ticket of a reporter: the report, the public notes and the status changes. */
export interface MyTicketDetail extends MyTicketItem {
  readonly body: string;
  readonly attachments: readonly TicketAttachment[];
  readonly notes: readonly TicketNote[];
  /** Status changes only, without an actor. */
  readonly events: readonly {
    readonly id: Uuid;
    readonly kind: 'status';
    readonly at: IsoDateTime;
    readonly payload: TicketEventPayload;
  }[];
  readonly closedAt: IsoDateTime | null;
  /** False while a block holds back the reporter. */
  readonly canReply: boolean;
}

export interface MyTicketPage {
  readonly items: readonly MyTicketItem[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface TicketPatch {
  readonly status?: TicketStatus;
  /** Explicit null unassigns. */
  readonly assigneeId?: Uuid | null;
  readonly kind?: TicketKind;
  /** Only with status `rejected`. */
  readonly duplicateOfId?: Uuid;
  /** Only with status `done` or `rejected`. */
  readonly completeTodos?: boolean;
}

export interface TicketCounts {
  readonly new: number;
  readonly inProgress: number;
  readonly done: number;
  readonly rejected: number;
}

/** A quiet read; `detail` also keeps it in the HTTP cache. */
function readContext(opts: { readonly detail?: boolean }): HttpContext {
  return opts.detail ? detailContext() : skipLoading();
}

/** The filters of `GET /tickets`. */
export interface TicketQuery {
  readonly status?: readonly TicketStatus[];
  readonly kind?: readonly TicketKind[];
  /** A principal id, `me` or `none`. */
  readonly assignee?: string | null;
  readonly q?: string | null;
  readonly limit?: number;
  readonly offset?: number;
}

export interface TicketPage {
  readonly items: readonly TicketListItem[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

@Injectable({ providedIn: 'root' })
export class TicketsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** Send a ticket. Without a session the body carries `email` and `altcha`. */
  create(body: TicketCreate): Observable<TicketCreated> {
    return this.http.post<TicketCreated>(`${this.base}/tickets`, body);
  }

  list(query: TicketQuery = {}): Observable<TicketPage> {
    return this.http.get<TicketPage>(`${this.base}/tickets`, { params: queryParams(query), context: skipLoading() });
  }

  /** The own tickets of the caller; `assignee` does not apply. */
  mine(query: TicketQuery = {}): Observable<MyTicketPage> {
    const params = queryParams({ ...query, assignee: null });
    return this.http.get<MyTicketPage>(`${this.base}/tickets/mine`, { params, context: skipLoading() });
  }

  /** `detail` keeps the answer for the read ahead of the list (`prefetchDetails`). */
  getMine(id: Uuid, opts: { detail?: boolean } = {}): Observable<MyTicketDetail> {
    return this.http.get<MyTicketDetail>(`${this.base}/tickets/mine/${id}`, { context: readContext(opts) });
  }

  /** A message of the reporter: always public. */
  addMyNote(id: Uuid, body: string, files: MessageFiles = {}): Observable<TicketNote> {
    return this.http.post<TicketNote>(`${this.base}/tickets/mine/${id}/notes`, {
      body,
      ...messageFiles(files),
    });
  }

  editMyNote(id: Uuid, noteId: Uuid, body: string): Observable<TicketNote> {
    return this.http.patch<TicketNote>(`${this.base}/tickets/mine/${id}/notes/${noteId}`, { body });
  }

  deleteMyNote(id: Uuid, noteId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/tickets/mine/${id}/notes/${noteId}`);
  }

  /** The counts per state, for the rail badge. Never covers the page. */
  counts(): Observable<TicketCounts> {
    return this.http.get<TicketCounts>(`${this.base}/tickets/counts`, { context: skipLoading() });
  }

  /** The people a ticket can go to, by name. */
  assignees(): Observable<PersonRef[]> {
    return this.http.get<PersonRef[]>(`${this.base}/tickets/assignees`, { context: skipLoading() });
  }

  /** `detail` keeps the answer for the read ahead of the list (`prefetchDetails`). */
  get(id: Uuid, opts: { detail?: boolean } = {}): Observable<TicketDetail> {
    return this.http.get<TicketDetail>(`${this.base}/tickets/${id}`, { context: readContext(opts) });
  }

  patch(id: Uuid, body: TicketPatch): Observable<TicketDetail> {
    return this.http.patch<TicketDetail>(`${this.base}/tickets/${id}`, body);
  }

  /**
   * A note; `files` binds draft uploads of `POST /apply/attachments` (at most 5).
   * Without `visibility` the server keeps the note internal.
   */
  addNote(
    id: Uuid,
    body: string,
    files: MessageFiles = {},
    visibility?: TicketNoteVisibility,
    mentions?: Uuid[],
  ): Observable<TicketNote> {
    return this.http.post<TicketNote>(`${this.base}/tickets/${id}/notes`, {
      body,
      ...(mentions?.length ? { mentions } : {}),
      ...messageFiles(files),
      ...(visibility ? { visibility } : {}),
    });
  }

  /** Change a note; `mentions` replaces the people it mentions, without it they stay. */
  editNote(id: Uuid, noteId: Uuid, body: string, mentions?: Uuid[]): Observable<TicketNote> {
    return this.http.patch<TicketNote>(
      `${this.base}/tickets/${id}/notes/${noteId}`,
      mentions ? { body, mentions } : { body },
    );
  }

  deleteNote(id: Uuid, noteId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/tickets/${id}/notes/${noteId}`);
  }

  /** Block the reporter: the account, or the e-mail of a report without one. Idempotent. */
  blockSender(id: Uuid): Observable<TicketDetail> {
    return this.http.post<TicketDetail>(`${this.base}/tickets/${id}/block-sender`, null);
  }

  /** Lift the block of the reporter. Idempotent. */
  unblockSender(id: Uuid): Observable<TicketDetail> {
    return this.http.delete<TicketDetail>(`${this.base}/tickets/${id}/block-sender`);
  }

  /** The blocked senders, newest first. */
  blockedSenders(): Observable<TicketBlockedSender[]> {
    return this.http.get<TicketBlockedSender[]>(`${this.base}/tickets/blocked-senders`, {
      context: skipLoading(),
    });
  }

  deleteBlockedSender(blockId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/tickets/blocked-senders/${blockId}`);
  }

  /** The download of a ticket attachment: streamed through the API, never presigned. */
  attachmentUrl(attachmentId: Uuid): string {
    return `${this.base}/attachments/${attachmentId}/download`;
  }
}

/** The query params of a ticket list. */
function queryParams(query: TicketQuery): HttpParams {
  return httpParams({
    status: query.status ?? [],
    kind: query.kind ?? [],
    assignee: query.assignee || undefined,
    q: query.q?.trim() || undefined,
    limit: query.limit,
    offset: query.offset,
  });
}
