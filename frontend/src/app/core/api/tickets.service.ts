/**
 * API of the tickets (`/api/tickets`): the "Problem melden" dialog sends a ticket, and
 * the page `/tickets` reads and works them. A person works the tickets of a Bereich with
 * `ticket.manage` (every Bereich) or with the Gremium permission `ticket.work` in the
 * Gremium of the Bereich.
 *
 * A reporter account reads its own tickets under `/tickets/mine`: the report, the
 * public notes and the status changes, and it writes, edits and deletes its own
 * messages. Every other read and write below the create needs the work right; an
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
export type TicketStatus = 'new' | 'in_progress' | 'waiting' | 'done' | 'rejected';
/** The way a ticket came: the help menu, a mail, or a person of the team wrote it by hand. */
export type TicketSource = 'help' | 'mail' | 'team';

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
  /** Required for the Bereich "Plattform"; not sent for another Bereich. */
  readonly kind?: TicketKind;
  /** A Bereich of `reportAreas`; without it the report goes to "Plattform". */
  readonly areaId?: Uuid;
  /** A Kategorie of that Bereich. */
  readonly categoryId?: Uuid;
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

/** The only answer to the reporter: the number, for example "T-7K3QX9MD". */
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

/** A Kategorie of a Bereich. The Bereich "Plattform" has none: its Kategorien are the kinds. */
export interface TicketCategory {
  readonly id: Uuid;
  readonly name: string;
}

/** A Bereich: a group of tickets with its own team and its own Kategorien. */
export interface TicketArea {
  readonly id: Uuid;
  readonly name: string;
  /** The Gremium whose roles give `ticket.work`; null: only `ticket.manage` works here. */
  readonly gremiumId: Uuid | null;
  /** The built-in Bereich of the help menu reports. Nobody deletes it. */
  readonly platform: boolean;
  /** A new ticket sends a mail to the team of the Bereich. */
  readonly notifyNew: boolean;
  /** A signed-in person can choose the Bereich in the ticket dialog; always true for "Plattform". */
  readonly inApp: boolean;
  readonly categories: readonly TicketCategory[];
  /** The caller works in the Bereich. */
  readonly mine: boolean;
}

/** A Bereich that a signed-in person can choose in the ticket dialog of the help menu. */
export interface TicketAreaChoice {
  readonly id: Uuid;
  readonly name: string;
  readonly platform: boolean;
  readonly categories: readonly TicketCategory[];
}

/**
 * A ticket that a person of the team writes by hand for an account. `body` is the note of
 * the team, which the person does not read; `message` is the first public message.
 */
export interface TicketManualCreate {
  readonly areaId: Uuid;
  readonly title: string;
  readonly body: string;
  readonly kind?: TicketKind;
  readonly categoryId?: Uuid;
  readonly reporterId?: Uuid;
  /** Needs a Postfach of the Bereich (422 `ticket_area_without_mailbox`). */
  readonly email?: string;
  readonly message: string;
}

/** A reference to another ticket. */
export interface TicketRef {
  readonly id: Uuid;
  readonly number: string;
}

/** The answer to a message on a ticket that is closed for more than 14 days: the new ticket. */
export interface TicketFollowUp {
  readonly followUp: TicketRef;
}

/** A Kategorie in the save of a Bereich: `id` keeps a stored one, without it a new one. */
export interface TicketCategoryInput {
  readonly id?: Uuid | null;
  readonly name: string;
}

export interface TicketAreaInput {
  readonly name: string;
  readonly gremiumId: Uuid | null;
  readonly notifyNew: boolean;
  readonly inApp: boolean;
  /** The whole ordered list; a stored Kategorie that it leaves out is deleted. */
  readonly categories: readonly TicketCategoryInput[];
}

/** The Postfach of a Bereich, without its passwords (`admin.ticket_mail`). */
export interface TicketMailbox {
  readonly areaId: Uuid;
  readonly address: string;
  readonly imapHost: string;
  readonly imapPort: number;
  readonly imapUser: string;
  readonly smtpHost: string;
  readonly smtpPort: number;
  readonly smtpUser: string;
  /** The IMAP folder that takes each imported mail. */
  readonly doneFolder: string;
  readonly enabled: boolean;
  /** The text that ends each sent mail; `{name}` stands for the writer. */
  readonly signature?: string;
  /** "Eingang bestätigen": a new ticket from a mail gets a confirmation. */
  readonly confirm?: boolean;
  /** The cause code of the fetch after eight failed runs in sequence, else null. */
  readonly error?: string | null;
  readonly fetchedAt?: string | null;
}

/** The body of a new Postfach. A change sends a part of it; a password it leaves out stays. */
export interface TicketMailboxInput {
  readonly address: string;
  readonly imapHost: string;
  readonly imapPort: number;
  readonly imapUser: string;
  readonly imapPassword: string;
  readonly smtpHost: string;
  readonly smtpPort: number;
  readonly smtpUser: string;
  readonly smtpPassword: string;
  readonly doneFolder: string;
  readonly enabled: boolean;
  readonly signature: string;
  readonly confirm: boolean;
}

/** Each Postfach and the hosts of the deploy setting `TICKET_MAIL_HOST_ALLOWLIST`. */
export interface TicketMailboxList {
  readonly items: readonly TicketMailbox[];
  readonly allowedHosts: readonly string[];
}

/** The result of one connection of the test. `error` is the cause code of a failure. */
export interface TicketMailboxCheck {
  readonly ok: boolean;
  readonly error?: string | null;
}

export interface TicketMailboxTest {
  readonly imap: TicketMailboxCheck;
  readonly smtp: TicketMailboxCheck;
}

export interface TicketListItem {
  readonly id: Uuid;
  readonly number: string;
  /** The Bereich of the ticket. */
  readonly areaId: Uuid;
  /** The kind of a report; null outside the Bereich "Plattform". */
  readonly kind: TicketKind | null;
  /** The Kategorie of the Bereich; null in "Plattform" and without one. */
  readonly categoryId: Uuid | null;
  readonly title: string;
  readonly status: TicketStatus;
  /** Absent on an older server: the help menu. */
  readonly source?: TicketSource;
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

export type TicketEventKind =
  | 'created'
  | 'status'
  | 'assignee'
  | 'kind'
  | 'category'
  | 'area'
  | 'todo_done'
  | 'mail_auto';

/** The payloads of the event kinds, all optional so one type reads every kind. */
export interface TicketEventPayload {
  /** created */
  readonly confirmationSent?: boolean;
  /** mail_auto: the subject of the automatic mail. */
  readonly subject?: string | null;
  /** status, assignee, kind; category: the names; area: the ids */
  readonly from?: TicketStatus | TicketKind | PersonRef | string | null;
  readonly to?: TicketStatus | TicketKind | PersonRef | string | null;
  /** area: the names of both Bereiche at the time of the move. */
  readonly fromName?: string | null;
  readonly toName?: string | null;
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

/** A file of a mail that did not become a file of the message. */
export interface TicketSkippedFile {
  readonly name: string;
  readonly size: number;
  /** `size`: above the size limit; `type`: a type that an upload refuses. */
  readonly reason: 'size' | 'type';
}

/**
 * One mail of a ticket from a Postfach. `noteId` names the message that the mail became;
 * null for the first mail of the ticket and for an automatic mail. `source` tells if the
 * full source downloads: only a `clean` one does.
 */
export interface TicketMail {
  readonly id: Uuid;
  readonly noteId: Uuid | null;
  readonly direction: 'in' | 'out';
  readonly fromName: string | null;
  readonly fromAddress: string | null;
  readonly cc: readonly string[];
  readonly subject: string | null;
  readonly automatic: boolean;
  readonly source: 'clean' | 'infected' | 'closed' | 'gone';
  readonly sourceSize: number;
  readonly skipped: readonly TicketSkippedFile[];
  /** The `To` addresses of a sent mail. */
  readonly to?: readonly string[];
  /** The state of a sent mail; null for an imported mail. */
  readonly state?: 'sending' | 'sent' | 'failed' | null;
  /** The cause code of the newest failed send. */
  readonly error?: string | null;
  readonly at: IsoDateTime;
}

/** The addresses of a mail. */
export interface TicketMailRecipients {
  readonly to: readonly string[];
  readonly cc: readonly string[];
}

/**
 * The recipients of the next public message on a mail ticket. `enabled` is false while
 * the Postfach of the Bereich is off: a public message then answers 409 `mailbox_off`.
 */
export interface TicketMailAnswer extends TicketMailRecipients {
  readonly enabled: boolean;
}

export interface TicketDetail extends TicketListItem {
  readonly body: string;
  readonly context: TicketContext;
  readonly attachments: readonly TicketAttachment[];
  readonly notes: readonly TicketNote[];
  readonly events: readonly TicketEvent[];
  readonly duplicateOf: { readonly id: Uuid; readonly number: string } | null;
  /** The closed ticket that a late message of the sender answered. */
  readonly followUpOf?: TicketRef | null;
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
  /** The mails of a ticket from a Postfach, oldest first. Absent on an older server. */
  readonly mails?: readonly TicketMail[];
  /** The recipients of a public message on a mail ticket; null on another ticket. */
  readonly mailAnswer?: TicketMailAnswer | null;
  /**
   * The clean files that the person can file in Paperless; null without `paperless.use`
   * and while the Paperless connection is off.
   */
  readonly paperless?: TicketPaperless | null;
}

/** One clean file of a ticket with the state of its filing in Paperless. */
export interface TicketPaperlessFile {
  readonly id: Uuid;
  readonly filename: string;
  /** `none` before the action, `pending` while the job runs, `filed` with a document. */
  readonly state: 'none' | 'pending' | 'filed' | 'failed';
  /** The address of the document in Paperless; null before `filed`. */
  readonly url: string | null;
}

/** The files of a ticket for the action "In Paperless ablegen". */
export interface TicketPaperless {
  readonly files: readonly TicketPaperlessFile[];
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
  /** null after a move out of the Bereich "Plattform". */
  readonly kind: TicketKind | null;
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
  /** The ticket is closed for more than 14 days: a message becomes a new ticket. */
  readonly replyOpensNew?: boolean;
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
  /** A Kategorie of the Bereich of the ticket; explicit null clears it. */
  readonly categoryId?: Uuid | null;
  /** Move the ticket to this Bereich. The kind and the Kategorie go. */
  readonly areaId?: Uuid;
  /** Only with status `rejected`. */
  readonly duplicateOfId?: Uuid;
  /** Only with status `done` or `rejected`. */
  readonly completeTodos?: boolean;
}

export interface TicketCounts {
  readonly new: number;
  readonly inProgress: number;
  readonly waiting?: number;
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
  /** Only the tickets of these Bereiche. */
  readonly area?: readonly Uuid[];
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

  /** Each Postfach of the page "Hilfe & Tickets" (`admin.ticket_mail`). */
  adminMailboxes(): Observable<TicketMailboxList> {
    return this.http.get<TicketMailboxList>(`${this.base}/admin/ticket-mailboxes`, {
      context: skipLoading(),
    });
  }

  /** 409 `ticket_mailbox_exists`, 422 `mail_host_not_allowed`. */
  createMailbox(areaId: Uuid, body: TicketMailboxInput): Observable<TicketMailbox> {
    return this.http.post<TicketMailbox>(`${this.base}/admin/ticket-areas/${areaId}/mailbox`, body);
  }

  updateMailbox(areaId: Uuid, body: Partial<TicketMailboxInput>): Observable<TicketMailbox> {
    return this.http.patch<TicketMailbox>(`${this.base}/admin/ticket-areas/${areaId}/mailbox`, body);
  }

  deleteMailbox(areaId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/admin/ticket-areas/${areaId}/mailbox`);
  }

  /** Log in to both accounts of the stored Postfach. */
  testMailbox(areaId: Uuid): Observable<TicketMailboxTest> {
    return this.http.post<TicketMailboxTest>(
      `${this.base}/admin/ticket-areas/${areaId}/mailbox/test`,
      {},
    );
  }

  /** `detail` keeps the answer for the read ahead of the list (`prefetchDetails`). */
  getMine(id: Uuid, opts: { detail?: boolean } = {}): Observable<MyTicketDetail> {
    return this.http.get<MyTicketDetail>(`${this.base}/tickets/mine/${id}`, { context: readContext(opts) });
  }

  /** The Bereiche that a signed-in person can choose in the ticket dialog. */
  reportAreas(): Observable<TicketAreaChoice[]> {
    return this.http.get<TicketAreaChoice[]>(`${this.base}/tickets/report-areas`, { context: skipLoading() });
  }

  /** A ticket by hand for an account; the caller needs the work right in the Bereich. */
  createManual(body: TicketManualCreate): Observable<TicketDetail> {
    return this.http.post<TicketDetail>(`${this.base}/tickets/manual`, body);
  }

  /**
   * A message of the reporter: always public. On a ticket that is closed for more than
   * 14 days the answer is the new ticket that the message became.
   */
  addMyNote(id: Uuid, body: string, files: MessageFiles = {}): Observable<TicketNote | TicketFollowUp> {
    return this.http.post<TicketNote | TicketFollowUp>(`${this.base}/tickets/mine/${id}/notes`, {
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

  /** The people a ticket of the Bereich can go to, by name; without `area`: of every own Bereich. */
  assignees(area?: Uuid): Observable<PersonRef[]> {
    return this.http.get<PersonRef[]>(`${this.base}/tickets/assignees`, {
      params: httpParams({ area }),
      context: skipLoading(),
    });
  }

  /** Every Bereich by name, each with `mine`: a ticket can move to any of them. */
  areas(): Observable<TicketArea[]> {
    return this.http.get<TicketArea[]>(`${this.base}/tickets/areas`, { context: skipLoading() });
  }

  /** The Bereiche of the page "Hilfe & Tickets" (`admin.site`). */
  adminAreas(): Observable<TicketArea[]> {
    return this.http.get<TicketArea[]>(`${this.base}/admin/ticket-areas`, { context: skipLoading() });
  }

  createArea(body: TicketAreaInput): Observable<TicketArea> {
    return this.http.post<TicketArea>(`${this.base}/admin/ticket-areas`, body);
  }

  updateArea(id: Uuid, body: Partial<TicketAreaInput>): Observable<TicketArea> {
    return this.http.patch<TicketArea>(`${this.base}/admin/ticket-areas/${id}`, body);
  }

  /** 409 `ticket_area_has_tickets` while the Bereich holds a ticket. */
  deleteArea(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/admin/ticket-areas/${id}`);
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
    recipients?: TicketMailRecipients | null,
  ): Observable<TicketNote> {
    return this.http.post<TicketNote>(`${this.base}/tickets/${id}/notes`, {
      body,
      ...(recipients ? { to: recipients.to, cc: recipients.cc } : {}),
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

  /** "Erneut senden": start the send of a failed mail again. */
  resendMail(ticketId: Uuid, mailId: Uuid): Observable<TicketMail> {
    return this.http.post<TicketMail>(`${this.base}/tickets/${ticketId}/mails/${mailId}/resend`, {});
  }

  /**
   * "In Paperless ablegen": open the job that files one clean file of a ticket
   * (§F/integrations/ticket-mail/002742). The answer is the file with its new state.
   */
  fileInPaperless(ticketId: Uuid, attachmentId: Uuid): Observable<TicketPaperlessFile> {
    return this.http.post<TicketPaperlessFile>(
      `${this.base}/tickets/${ticketId}/files/${attachmentId}/paperless`,
      {},
    );
  }

  /** The download of the full source of a mail of a ticket (`.eml`). */
  mailSourceUrl(ticketId: Uuid, mailId: Uuid): string {
    return `${this.base}/tickets/${ticketId}/mails/${mailId}/source`;
  }
}

/** The query params of a ticket list. */
function queryParams(query: TicketQuery): HttpParams {
  return httpParams({
    status: query.status ?? [],
    kind: query.kind ?? [],
    area: query.area ?? [],
    assignee: query.assignee || undefined,
    q: query.q?.trim() || undefined,
    limit: query.limit,
    offset: query.offset,
  });
}
