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
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { IsoDateTime, MessageAttachment, MessageFiles, PersonRef, ScanState, Uuid } from '@core/api/models';
import { messageFiles } from '@core/api/mappers';
import { skipLoading } from '@core/loading/loading.interceptor';

export type TicketKind = 'bug' | 'question' | 'idea';
export type TicketStatus = 'new' | 'in_progress' | 'done' | 'rejected';

/** The kinds in the order of the dialog and the filter. */
export const TICKET_KINDS: readonly TicketKind[] = ['bug', 'question', 'idea'];
/** The states in the order of the list groups and the filter. */
export const TICKET_STATUSES: readonly TicketStatus[] = ['new', 'in_progress', 'done', 'rejected'];

/** What the dialog sends along: every field optional, capped by the server. */
export interface TicketContext {
  url?: string;
  route?: string;
  appVersion?: string;
  userAgent?: string;
  viewport?: string;
  language?: 'de' | 'en';
  colorScheme?: 'light' | 'dark';
}

export interface TicketCreate {
  kind: TicketKind;
  title: string;
  body: string;
  /** Required without a session; the server ignores it with one. */
  email?: string | null;
  context: TicketContext;
  attachmentIds?: Uuid[];
  draftToken?: string | null;
  /** Required without a session. */
  altcha?: string | null;
}

/** The only answer to the reporter: the number, for example "T-0042". */
export interface TicketCreated {
  number: string;
}

export interface TicketReporter {
  principalId: Uuid | null;
  displayName: string | null;
  /** The account e-mail or the given e-mail; null after the anonymization. */
  email: string | null;
  anonymized: boolean;
}

export interface TicketListItem {
  id: Uuid;
  number: string;
  kind: TicketKind;
  title: string;
  status: TicketStatus;
  reporter: TicketReporter;
  assignee: PersonRef | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

/** A file of the report. Only a `clean` file downloads, streamed through the API. */
export interface TicketAttachment {
  id: Uuid;
  filename: string;
  mime: string;
  size: number;
  /** The scan ended; it does not say whether it found anything. */
  scanned: boolean;
  /** The three-state scan of the server, as on a message file. */
  scanState?: ScanState;
}

export type TicketEventKind = 'created' | 'status' | 'assignee' | 'kind' | 'todo_done';

/** The payloads of the event kinds, all optional so one type reads every kind. */
export interface TicketEventPayload {
  /** created */
  confirmationSent?: boolean;
  /** status, assignee, kind */
  from?: TicketStatus | TicketKind | PersonRef | null;
  to?: TicketStatus | TicketKind | PersonRef | null;
  /** status: the number of the ticket this one duplicates. */
  duplicateOf?: string;
  /** todo_done */
  cardId?: Uuid;
  cardTitle?: string | null;
  boardId?: Uuid;
}

export interface TicketEvent {
  id: Uuid;
  kind: TicketEventKind;
  /** null: the system. */
  actor: PersonRef | null;
  at: IsoDateTime;
  payload: TicketEventPayload;
}

/** `internal`: the holders of `ticket.manage` only; `public`: the reporter account too. */
export type TicketNoteVisibility = 'internal' | 'public';

export interface TicketNote {
  id: Uuid;
  author: PersonRef;
  body: string;
  at: IsoDateTime;
  editedAt: IsoDateTime | null;
  isOwn: boolean;
  /** The files of the note, oldest first. */
  attachments: MessageAttachment[];
  /** Absent on an older server: internal. */
  visibility?: TicketNoteVisibility;
  /** The reporter wrote it. */
  fromReporter?: boolean;
  /** The people the note mentions; empty for the reporter. */
  mentions?: PersonRef[];
}

export interface TicketDetail extends TicketListItem {
  body: string;
  context: TicketContext;
  attachments: TicketAttachment[];
  notes: TicketNote[];
  events: TicketEvent[];
  duplicateOf: { id: Uuid; number: string } | null;
  /** The application or meeting of `context.route`, when the viewer may read it. */
  contextTarget: { kind: 'application' | 'meeting'; id: Uuid; title: string } | null;
  /** Linked cards that are open and readable. */
  openTodoCount: number;
  closedAt: IsoDateTime | null;
  anonymizedAt: IsoDateTime | null;
  /** The reporter is blocked; false for an anonymized ticket. */
  senderBlocked: boolean;
}

/**
 * A blocked sender of "Absender sperren". A report of a blocked sender gets a number,
 * but nothing is stored and no mail goes out.
 */
export interface TicketBlockedSender {
  id: Uuid;
  kind: 'principal' | 'email';
  /** kind `principal`. */
  person: PersonRef | null;
  /** kind `email`: the stored address; kind `principal`: the account e-mail. */
  email: string | null;
  /** null: a deleted person. */
  blockedBy: PersonRef | null;
  blockedAt: IsoDateTime;
  /** null after the ticket is gone. */
  sourceTicket: { id: Uuid; number: string } | null;
  /** Reports held back since the block. */
  hitCount: number;
  lastHitAt: IsoDateTime | null;
}

/** A ticket in the list of its reporter: no reporter, no assignee. */
export interface MyTicketItem {
  id: Uuid;
  number: string;
  kind: TicketKind;
  title: string;
  status: TicketStatus;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

/** The own ticket of a reporter: the report, the public notes and the status changes. */
export interface MyTicketDetail extends MyTicketItem {
  body: string;
  attachments: TicketAttachment[];
  notes: TicketNote[];
  /** Status changes only, without an actor. */
  events: { id: Uuid; kind: 'status'; at: IsoDateTime; payload: TicketEventPayload }[];
  closedAt: IsoDateTime | null;
  /** False while a block holds back the reporter. */
  canReply: boolean;
}

export interface MyTicketPage {
  items: MyTicketItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TicketPatch {
  status?: TicketStatus;
  /** Explicit null unassigns. */
  assigneeId?: Uuid | null;
  kind?: TicketKind;
  /** Only with status `rejected`. */
  duplicateOfId?: Uuid;
  /** Only with status `done` or `rejected`. */
  completeTodos?: boolean;
}

export interface TicketCounts {
  new: number;
  inProgress: number;
  done: number;
  rejected: number;
}

/** The filters of `GET /tickets`. */
export interface TicketQuery {
  status?: readonly TicketStatus[];
  kind?: readonly TicketKind[];
  /** A principal id, `me` or `none`. */
  assignee?: string | null;
  q?: string | null;
  limit?: number;
  offset?: number;
}

export interface TicketPage {
  items: TicketListItem[];
  total: number;
  limit: number;
  offset: number;
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

  getMine(id: Uuid): Observable<MyTicketDetail> {
    return this.http.get<MyTicketDetail>(`${this.base}/tickets/mine/${id}`, { context: skipLoading() });
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

  get(id: Uuid): Observable<TicketDetail> {
    return this.http.get<TicketDetail>(`${this.base}/tickets/${id}`, { context: skipLoading() });
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
  let params = new HttpParams();
  for (const s of query.status ?? []) params = params.append('status', s);
  for (const k of query.kind ?? []) params = params.append('kind', k);
  if (query.assignee) params = params.set('assignee', query.assignee);
  const q = query.q?.trim();
  if (q) params = params.set('q', q);
  if (query.limit !== undefined) params = params.set('limit', query.limit);
  if (query.offset !== undefined) params = params.set('offset', query.offset);
  return params;
}
