/**
 * API of the to-dos (`/api/todos`): boards, cards and their links.
 *
 * A board is a gremium board (members with `todo.write`), a personal board (the owner)
 * or a team board (holders of its permission). A board or a card the caller may not read
 * answers 404. The client only binds the data; the server stays authoritative.
 */
import { HttpClient, HttpErrorResponse, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { catchError, map, of, throwError, type Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { I18nMap, IsoDateTime, MessageAttachment, MessageFiles, Page, PersonRef, Uuid } from '@core/api/models';
import { messageFiles } from '@core/api/mappers';
import { skipLoading } from '@stupa-makers/ui-kit';
import { detailContext } from '@core/cache/cache.interceptor';
import type { TicketStatus } from './tickets.service';
import { httpParams } from './http-params';

export type TodoBoardKind = 'gremium' | 'personal' | 'team';
export type TodoLabelColor = 'green' | 'blue' | 'violet' | 'amber' | 'red' | 'gray';
export type TodoLinkKind =
  | 'application'
  | 'meeting'
  | 'agenda_item'
  | 'vote'
  | 'gremium'
  | 'invoice'
  | 'expense'
  | 'ticket'
  | 'todo';
export type TodoVoteStatus = 'draft' | 'open' | 'closed' | 'cancelled';
export type TodoVoteResult = 'passed' | 'rejected' | 'tie' | 'elected' | 'runoff';

export interface TodoBoardSummary {
  readonly id: Uuid;
  readonly name: string;
  readonly kind: TodoBoardKind;
  readonly gremiumId: Uuid | null;
  readonly canWrite: boolean;
  readonly canConfigure: boolean;
  /** Not archived, not in the done column. */
  readonly openCount: number;
}

export interface TodoColumn {
  readonly id: Uuid;
  readonly name: string;
  readonly position: number;
  readonly isDone: boolean;
  readonly cardCount: number;
}

export interface TodoLabel {
  readonly id: Uuid;
  readonly name: string;
  readonly color: TodoLabelColor;
}

/** The facts of a link target; only the fields of its kind are set. */
export interface TodoLinkDetail {
  readonly stateLabel?: I18nMap | null;
  readonly date?: string | null;
  readonly meetingTitle?: string | null;
  readonly position?: number | null;
  readonly number?: string | null;
  readonly status?: TicketStatus | null;
  readonly boardName?: string | null;
  readonly columnName?: string | null;
  readonly isDone?: boolean | null;
  /** Invoice (gross) or booking amount, a decimal string in EUR. */
  readonly amount?: string | null;
  /** The supplier of an invoice, the correspondent of a booking. */
  readonly counterparty?: string | null;
  /** The path key of the cost centre of a booking ("VS-800-04"). */
  readonly costCentre?: string | null;
  readonly invoiceStatus?: 'open' | 'paid' | null;
  readonly bookingKind?: 'expense' | 'income' | null;
  readonly voteStatus?: TodoVoteStatus | null;
  readonly voteResult?: TodoVoteResult | null;
}

export interface TodoLink {
  readonly id: Uuid;
  readonly kind: TodoLinkKind;
  readonly targetId: Uuid;
  /** false: title, url and detail are null ("<Kind> (kein Zugriff)"). */
  readonly accessible: boolean;
  readonly title: string | null;
  readonly url: string | null;
  readonly detail: TodoLinkDetail | null;
  /** Readable only through this card (spec 000487): no url, the card opens a read sheet. */
  readonly granted?: boolean;
}

/** One fact of a link target in the read sheet; `label` is the label of a form field. */
export interface TodoViewFact {
  readonly key: string;
  readonly label: Readonly<Record<string, string>> | null;
  readonly value: string;
  readonly format: 'text' | 'money' | 'date' | 'markdown';
}

/** A TOP of a meeting, a vote of a TOP (`meta`: result or status) or a checklist item. */
export interface TodoViewRow {
  readonly title: string;
  readonly meta: string | null;
  readonly done: boolean | null;
}

/** A link target as a card reader sees it: read only, without PII and without links. */
export interface TodoLinkView {
  readonly kind: TodoLinkKind;
  readonly title: string;
  readonly detail: TodoLinkDetail;
  readonly facts: readonly TodoViewFact[];
  readonly rows: readonly TodoViewRow[];
}

/** The event data of a card: the card is an Event (`Veranstaltung`). Dates are `YYYY-MM-DD`. */
export interface TodoEventBrief {
  readonly startsOn: string | null;
  readonly endsOn: string | null;
  readonly place: string | null;
  readonly participants: number | null;
  readonly seriesId: Uuid | null;
  readonly seriesName: string | null;
}

/** The money of an Event: decimal strings with two places; balance = income − expenses. */
export interface TodoEventTotals {
  readonly requested: string;
  readonly approved: string;
  readonly expenses: string;
  readonly income: string;
  readonly balance: string;
}

/** A decision of an Event: the valid decision of a linked Antrag or a closed vote. */
export interface TodoEventDecision {
  readonly kind: 'decision' | 'vote';
  readonly targetId: Uuid | null;
  readonly title: string;
  readonly decidedAt: IsoDateTime | null;
  readonly meetingTitle: string | null;
  readonly result: string | null;
  readonly amount: string | null;
  readonly conditions: readonly string[];
}

/** Another Event of the series that the caller reads. */
export interface TodoEventEdition {
  readonly id: Uuid;
  readonly boardId: Uuid;
  readonly boardName: string;
  readonly title: string;
  readonly startsOn: string | null;
  readonly endsOn: string | null;
  readonly archived: boolean;
  readonly totals: TodoEventTotals;
}

/** What an Event gathers: totals, decisions, the other editions of its series. */
export interface TodoEventFacts {
  readonly totals: TodoEventTotals;
  readonly decisions: readonly TodoEventDecision[];
  readonly editions: readonly TodoEventEdition[];
  /** The other editions that the caller cannot read. */
  readonly hiddenEditions: number;
}

/** The event data to set (`PUT /todos/cards/{id}/event`) or to create a card with. */
export interface TodoEventIn {
  readonly startsOn?: string | null;
  readonly endsOn?: string | null;
  readonly place?: string | null;
  readonly participants?: number | null;
  readonly seriesId?: Uuid | null;
}

export interface TodoEventSeries {
  readonly id: Uuid;
  readonly name: string;
}

/** An Event on a board that the caller writes: an option of the `Veranstaltung` picker. */
export interface TodoEventRef {
  readonly id: Uuid;
  readonly boardId: Uuid;
  readonly boardName: string;
  readonly title: string;
  readonly startsOn: string | null;
  readonly endsOn: string | null;
}

export interface TodoCardTile {
  readonly id: Uuid;
  readonly boardId: Uuid;
  readonly columnId: Uuid;
  readonly rank: string;
  readonly title: string;
  /** `YYYY-MM-DD`. */
  readonly dueDate: string | null;
  readonly completedAt: IsoDateTime | null;
  readonly labelIds: readonly Uuid[];
  readonly assignees: readonly PersonRef[];
  readonly checklist: { readonly done: number; readonly total: number };
  readonly commentCount: number;
  readonly primaryLink: TodoLink | null;
  readonly linkCount: number;
  /** Set for an Event. */
  readonly event: TodoEventBrief | null;
  readonly version: number;
  readonly createdAt: IsoDateTime;
  readonly updatedAt: IsoDateTime;
}

export interface TodoBoard {
  readonly id: Uuid;
  readonly name: string;
  readonly kind: TodoBoardKind;
  readonly gremiumId: Uuid | null;
  readonly archiveAfterDays: number | null;
  readonly canWrite: boolean;
  readonly canConfigure: boolean;
  readonly columns: readonly TodoColumn[];
  readonly labels: readonly TodoLabel[];
  readonly cards: readonly TodoCardTile[];
  readonly archivedCount: number;
}

export interface TodoCheckItem {
  readonly id: Uuid;
  readonly text: string;
  readonly done: boolean;
  readonly position: number;
}

export type TodoEventKind =
  | 'created'
  | 'moved'
  | 'assigned'
  | 'due'
  | 'linked'
  | 'unlinked'
  | 'checklist'
  | 'renamed'
  | 'archived'
  | 'restored';

export interface TodoEvent {
  readonly id: Uuid;
  readonly kind: TodoEventKind;
  readonly actor: PersonRef | null;
  readonly at: IsoDateTime;
  readonly payload: Readonly<Record<string, unknown>>;
}

export interface TodoComment {
  readonly id: Uuid;
  readonly author: PersonRef;
  readonly body: string;
  readonly mentions: readonly PersonRef[];
  readonly at: IsoDateTime;
  readonly editedAt: IsoDateTime | null;
  readonly isOwn: boolean;
  /** The files of the comment, oldest first. */
  readonly attachments: readonly MessageAttachment[];
}

export interface TodoCardDetail extends TodoCardTile {
  readonly descriptionMd: string | null;
  readonly boardName: string;
  readonly boardKind: TodoBoardKind;
  readonly canWrite: boolean;
  readonly columns: readonly {
    readonly id: Uuid;
    readonly name: string;
    readonly isDone: boolean;
  }[];
  readonly labels: readonly TodoLabel[];
  readonly boardLabels: readonly TodoLabel[];
  readonly createdBy: PersonRef;
  readonly links: readonly TodoLink[];
  readonly checklistItems: readonly TodoCheckItem[];
  readonly events: readonly TodoEvent[];
  readonly comments: readonly TodoComment[];
  readonly archivedAt: IsoDateTime | null;
  /** Set for an Event. */
  readonly eventFacts: TodoEventFacts | null;
}

export interface TodoCardCreate {
  readonly boardId: Uuid;
  /** Default: the first column by position. */
  readonly columnId?: Uuid;
  readonly title: string;
  readonly descriptionMd?: string | null;
  readonly dueDate?: string | null;
  readonly assigneeIds?: readonly Uuid[];
  readonly labelIds?: readonly Uuid[];
  readonly links?: readonly { readonly kind: TodoLinkKind; readonly targetId: Uuid }[];
  /** Makes the card an Event. */
  readonly event?: TodoEventIn | null;
}

/** Content edits; `version` guards them (409 `card_version_conflict`). */
export interface TodoCardPatch {
  readonly version: number;
  readonly title?: string;
  readonly descriptionMd?: string | null;
  readonly dueDate?: string | null;
}

/** A move: `beforeId` places the card directly above that card, `afterId` directly
 *  below it; neither puts it at the end of the column. */
export interface TodoCardMove {
  readonly columnId: Uuid;
  readonly beforeId?: Uuid | null;
  readonly afterId?: Uuid | null;
}

/**
 * A move to another board: into `columnId` (default: the first column), between
 * `afterId` (above) and `beforeId` (below) as in a move, else at the end.
 */
export interface TodoCardTransfer {
  readonly boardId: Uuid;
  readonly columnId?: Uuid | null;
  readonly beforeId?: Uuid | null;
  readonly afterId?: Uuid | null;
}

export interface TodoMineItem extends TodoCardTile {
  readonly boardName: string;
  readonly boardKind: TodoBoardKind;
  readonly columnName: string;
  readonly labels: readonly TodoLabel[];
}

/** The open cards assigned to the caller over all boards. */
export interface TodoMine {
  readonly items: readonly TodoMineItem[];
  /** Cards due within 7 days, overdue included. */
  readonly dueSoonCount: number;
}

/**
 * A board of `GET /todos/mine/boards` (the rows under "Meine To-Dos") or of
 * `GET /todos/all/boards` (the meta-board "Alle"): all its columns and labels, and its
 * live cards (done ones too): under "mine" only the ones assigned to the caller, under
 * "all" every one. `cardCount` of a column counts those cards.
 */
export interface TodoAssignedBoard {
  readonly id: Uuid;
  readonly name: string;
  readonly kind: TodoBoardKind;
  readonly gremiumId: Uuid | null;
  readonly canWrite: boolean;
  readonly columns: readonly TodoColumn[];
  readonly labels: readonly TodoLabel[];
  readonly cards: readonly TodoCardTile[];
}

/** The answer of a poll of the rows: the boards and their ETag, or `boards: null` for 304. */
export interface TodoAssignedPoll {
  readonly boards: readonly TodoAssignedBoard[] | null;
  readonly etag: string | null;
}

/** A hit of the link picker. */
export interface TodoLinkTarget {
  readonly kind: TodoLinkKind;
  readonly targetId: Uuid;
  readonly title: string;
  readonly detail: TodoLinkDetail;
}

/** The board settings a configurer may change. */
export interface TodoBoardPatch {
  readonly name?: string;
  readonly archiveAfterDays?: number | null;
}

/** The answer of a poll: a new board and its ETag, or `board: null` for 304. */
export interface TodoBoardPoll {
  readonly board: TodoBoard | null;
  readonly etag: string | null;
}

/** A card that links an application, a meeting, an agenda item or a ticket. */
export interface TodoLinkedCard {
  readonly id: Uuid;
  readonly boardId: Uuid;
  readonly boardName: string;
  readonly title: string;
  readonly columnName: string;
  readonly isDone: boolean;
  readonly dueDate: string | null;
  readonly assignees: readonly PersonRef[];
  /** Set for an Event; then `balance` is its balance. */
  readonly event: TodoEventBrief | null;
  readonly balance: string | null;
}

/** An assignable person of a board; also the @-mention list. */
export interface TodoMember {
  readonly principalId: Uuid;
  readonly displayName: string | null;
}

/** The most cards that one `cards()` read asks for (`CARD_BATCH` of the API). */
export const CARD_BATCH = 50;

@Injectable({ providedIn: 'root' })
export class TodosApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** The boards of the caller: personal, the gremium boards by name, team. */
  boards(gremiumId?: Uuid | null): Observable<TodoBoardSummary[]> {
    const params = httpParams({ gremiumId: gremiumId || undefined });
    return this.http.get<TodoBoardSummary[]>(`${this.base}/todos/boards`, {
      params,
      context: skipLoading(),
    });
  }

  board(boardId: Uuid): Observable<TodoBoard> {
    return this.http.get<TodoBoard>(`${this.base}/todos/boards/${boardId}`, { context: skipLoading() });
  }

  /**
   * Read the board again with `If-None-Match`. A 304 gives `board: null`, so the caller
   * keeps its state.
   */
  pollBoard(boardId: Uuid, etag: string | null): Observable<TodoBoardPoll> {
    const headers = etag ? new HttpHeaders().set('If-None-Match', etag) : new HttpHeaders();
    return this.http
      .get<TodoBoard>(`${this.base}/todos/boards/${boardId}`, {
        headers,
        observe: 'response',
        context: skipLoading(),
      })
      .pipe(
        map((res) => ({ board: res.body, etag: res.headers.get('ETag') })),
        catchError((err: unknown) =>
          err instanceof HttpErrorResponse && err.status === 304
            ? of({ board: null, etag })
            : throwError(() => err),
        ),
      );
  }

  patchBoard(boardId: Uuid, body: TodoBoardPatch): Observable<TodoBoard> {
    return this.http.patch<TodoBoard>(`${this.base}/todos/boards/${boardId}`, body, {
      context: skipLoading(),
    });
  }

  addColumn(boardId: Uuid, name: string): Observable<TodoBoard> {
    return this.http.post<TodoBoard>(`${this.base}/todos/boards/${boardId}/columns`, { name }, {
      context: skipLoading(),
    });
  }

  patchColumn(boardId: Uuid, columnId: Uuid, body: { name?: string; isDone?: true }): Observable<TodoBoard> {
    return this.http.patch<TodoBoard>(`${this.base}/todos/boards/${boardId}/columns/${columnId}`, body, {
      context: skipLoading(),
    });
  }

  orderColumns(boardId: Uuid, columnIds: Uuid[]): Observable<TodoBoard> {
    return this.http.put<TodoBoard>(
      `${this.base}/todos/boards/${boardId}/columns/order`,
      { columnIds },
      { context: skipLoading() },
    );
  }

  /** Delete a column; `moveTo` takes its cards. */
  deleteColumn(boardId: Uuid, columnId: Uuid, moveTo?: Uuid | null): Observable<TodoBoard> {
    const params = httpParams({ moveTo: moveTo || undefined });
    return this.http.delete<TodoBoard>(`${this.base}/todos/boards/${boardId}/columns/${columnId}`, {
      params,
      context: skipLoading(),
    });
  }

  addLabel(boardId: Uuid, body: { name: string; color: TodoLabelColor }): Observable<TodoLabel> {
    return this.http.post<TodoLabel>(`${this.base}/todos/boards/${boardId}/labels`, body, {
      context: skipLoading(),
    });
  }

  patchLabel(boardId: Uuid, labelId: Uuid, body: { name?: string; color?: TodoLabelColor }): Observable<TodoLabel> {
    return this.http.patch<TodoLabel>(`${this.base}/todos/boards/${boardId}/labels/${labelId}`, body, {
      context: skipLoading(),
    });
  }

  deleteLabel(boardId: Uuid, labelId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/todos/boards/${boardId}/labels/${labelId}`, {
      context: skipLoading(),
    });
  }

  /** The archived cards of a board, newest first. */
  archive(boardId: Uuid, q = '', offset = 0, limit = 50, eventsOnly = false): Observable<Page<TodoCardTile>> {
    const params = httpParams({
      limit,
      offset,
      q: q || undefined,
      events: eventsOnly ? 'true' : undefined,
    });
    return this.http.get<Page<TodoCardTile>>(`${this.base}/todos/boards/${boardId}/archive`, {
      params,
      context: skipLoading(),
    });
  }

  members(boardId: Uuid, opts: { detail?: boolean } = {}): Observable<TodoMember[]> {
    return this.http.get<TodoMember[]>(`${this.base}/todos/boards/${boardId}/members`, {
      context: opts.detail ? detailContext() : skipLoading(),
    });
  }

  createCard(body: TodoCardCreate): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(`${this.base}/todos/cards`, body);
  }

  /** `detail` keeps the answer for the read ahead of a list (`prefetchDetails`). */
  card(cardId: Uuid, opts: { detail?: boolean } = {}): Observable<TodoCardDetail> {
    return this.http.get<TodoCardDetail>(`${this.base}/todos/cards/${cardId}`, {
      context: opts.detail ? detailContext() : skipLoading(),
    });
  }

  /**
   * Many whole cards at once (at most `CARD_BATCH`), in the order of `ids`: the read-ahead
   * of the board page. A card the caller cannot read is left out.
   */
  cards(ids: readonly Uuid[]): Observable<TodoCardDetail[]> {
    const params = httpParams({ ids });
    return this.http.get<TodoCardDetail[]>(`${this.base}/todos/cards`, { params, context: skipLoading() });
  }

  /** The tile of a live card, as the board read has it: what a live ping reads (404 when archived). */
  cardTile(cardId: Uuid): Observable<TodoCardTile> {
    return this.http.get<TodoCardTile>(`${this.base}/todos/cards/${cardId}/tile`, { context: skipLoading() });
  }

  /** The read sheet of a link of the card (spec 000487). */
  linkView(cardId: Uuid, linkId: Uuid): Observable<TodoLinkView> {
    return this.http.get<TodoLinkView>(`${this.base}/todos/cards/${cardId}/links/${linkId}/view`, {
      context: skipLoading(),
    });
  }

  patchCard(cardId: Uuid, body: TodoCardPatch): Observable<TodoCardDetail> {
    return this.http.patch<TodoCardDetail>(`${this.base}/todos/cards/${cardId}`, body, {
      context: skipLoading(),
    });
  }

  moveCard(cardId: Uuid, body: TodoCardMove): Observable<TodoCardTile> {
    return this.http.post<TodoCardTile>(`${this.base}/todos/cards/${cardId}/move`, body, {
      context: skipLoading(),
    });
  }

  /** Move a card to another board. Labels without a match there and assignees
   *  without access to it are dropped. */
  transferCard(cardId: Uuid, body: TodoCardTransfer): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/transfer`, body, {
      context: skipLoading(),
    });
  }

  /** Archive a card (the server keeps it). */
  archiveCard(cardId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/todos/cards/${cardId}`, { context: skipLoading() });
  }

  restoreCard(cardId: Uuid): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/restore`, null, {
      context: skipLoading(),
    });
  }

  addAssignee(cardId: Uuid, principalId: Uuid): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(
      `${this.base}/todos/cards/${cardId}/assignees`,
      { principalId },
      { context: skipLoading() },
    );
  }

  removeAssignee(cardId: Uuid, principalId: Uuid): Observable<TodoCardDetail> {
    return this.http.delete<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/assignees/${principalId}`, {
      context: skipLoading(),
    });
  }

  addCardLabel(cardId: Uuid, labelId: Uuid): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/labels`, { labelId }, {
      context: skipLoading(),
    });
  }

  removeCardLabel(cardId: Uuid, labelId: Uuid): Observable<TodoCardDetail> {
    return this.http.delete<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/labels/${labelId}`, {
      context: skipLoading(),
    });
  }

  addCheckItem(cardId: Uuid, text: string): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/checklist`, { text }, {
      context: skipLoading(),
    });
  }

  patchCheckItem(
    cardId: Uuid,
    itemId: Uuid,
    body: { text?: string; done?: boolean; position?: number },
  ): Observable<TodoCardDetail> {
    return this.http.patch<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/checklist/${itemId}`, body, {
      context: skipLoading(),
    });
  }

  deleteCheckItem(cardId: Uuid, itemId: Uuid): Observable<TodoCardDetail> {
    return this.http.delete<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/checklist/${itemId}`, {
      context: skipLoading(),
    });
  }

  addLink(cardId: Uuid, kind: TodoLinkKind, targetId: Uuid): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(
      `${this.base}/todos/cards/${cardId}/links`,
      { kind, targetId },
      { context: skipLoading() },
    );
  }

  removeLink(cardId: Uuid, linkId: Uuid): Observable<TodoCardDetail> {
    return this.http.delete<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/links/${linkId}`, {
      context: skipLoading(),
    });
  }

  /** A comment; `files` binds draft uploads of `POST /apply/attachments` (at most 5). */
  addComment(
    cardId: Uuid,
    body: string,
    mentions: Uuid[] = [],
    files: MessageFiles = {},
  ): Observable<TodoComment> {
    return this.http.post<TodoComment>(
      `${this.base}/todos/cards/${cardId}/comments`,
      { body, mentions, ...messageFiles(files) },
      { context: skipLoading() },
    );
  }

  editComment(cardId: Uuid, commentId: Uuid, body: string, mentions: Uuid[] = []): Observable<TodoComment> {
    return this.http.patch<TodoComment>(
      `${this.base}/todos/cards/${cardId}/comments/${commentId}`,
      { body, mentions },
      { context: skipLoading() },
    );
  }

  deleteComment(cardId: Uuid, commentId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/todos/cards/${cardId}/comments/${commentId}`, {
      context: skipLoading(),
    });
  }

  /** The open cards assigned to the caller, for "Aufgaben" and the rail counter. */
  mine(): Observable<TodoMine> {
    return this.http.get<TodoMine>(`${this.base}/todos/mine`, { context: skipLoading() });
  }

  /**
   * The other boards with the cards assigned to the caller, with `If-None-Match`. A 304
   * gives `boards: null`, so the caller keeps its state.
   */
  pollMineBoards(etag: string | null): Observable<TodoAssignedPoll> {
    return this.pollRows('mine', etag);
  }

  /**
   * Every readable board with all its live cards, the personal one first (the meta-board
   * "Alle"), with `If-None-Match`. A 304 gives `boards: null`.
   */
  pollAllBoards(etag: string | null): Observable<TodoAssignedPoll> {
    return this.pollRows('all', etag);
  }

  private pollRows(source: 'mine' | 'all', etag: string | null): Observable<TodoAssignedPoll> {
    const headers = etag ? new HttpHeaders().set('If-None-Match', etag) : new HttpHeaders();
    return this.http
      .get<TodoAssignedBoard[]>(`${this.base}/todos/${source}/boards`, {
        headers,
        observe: 'response',
        context: skipLoading(),
      })
      .pipe(
        map((res) => ({ boards: res.body, etag: res.headers.get('ETag') })),
        catchError((err: unknown) =>
          err instanceof HttpErrorResponse && err.status === 304
            ? of({ boards: null, etag })
            : throwError(() => err),
        ),
      );
  }

  /** The link picker: what the caller may read, at most five per kind. */
  linkTargets(q: string, kind: TodoLinkKind | 'all', excludeCardId?: Uuid | null): Observable<TodoLinkTarget[]> {
    const params = httpParams({ q, kind, excludeCardId: excludeCardId || undefined });
    return this.http.get<TodoLinkTarget[]>(`${this.base}/todos/link-targets`, {
      params,
      context: skipLoading(),
    });
  }

  /** The readable, not archived cards that link the target: open first, then by due date. */
  linked(kind: Exclude<TodoLinkKind, 'todo'>, targetId: Uuid): Observable<TodoLinkedCard[]> {
    const params = new HttpParams().set('kind', kind).set('targetId', targetId);
    return this.http.get<TodoLinkedCard[]>(`${this.base}/todos/linked`, {
      params,
      context: detailContext(),
    });
  }

  /** Set the event data; a to-do becomes an Event for good. */
  setEvent(cardId: Uuid, body: TodoEventIn): Observable<TodoCardDetail> {
    return this.http.put<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/event`, body, {
      context: skipLoading(),
    });
  }

  /** `Folgeveranstaltung anlegen`: the next edition in the first column. */
  followUp(cardId: Uuid): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(`${this.base}/todos/cards/${cardId}/follow-up`, null);
  }

  series(q = ''): Observable<TodoEventSeries[]> {
    const params = httpParams({ q: q || undefined });
    return this.http.get<TodoEventSeries[]>(`${this.base}/todos/series`, { params, context: skipLoading() });
  }

  createSeries(name: string): Observable<TodoEventSeries> {
    return this.http.post<TodoEventSeries>(`${this.base}/todos/series`, { name }, { context: skipLoading() });
  }

  /** The live Events on boards that the caller writes (the `Veranstaltung` picker). */
  writableEvents(q = ''): Observable<TodoEventRef[]> {
    const params = httpParams({ q: q || undefined });
    return this.http.get<TodoEventRef[]>(`${this.base}/todos/events`, { params, context: skipLoading() });
  }
}
