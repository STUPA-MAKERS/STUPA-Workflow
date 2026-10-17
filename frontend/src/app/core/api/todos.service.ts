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
import { skipLoading } from '@core/loading/loading.interceptor';
import type { TicketStatus } from './tickets.service';

export type TodoBoardKind = 'gremium' | 'personal' | 'team';
export type TodoLabelColor = 'green' | 'blue' | 'violet' | 'amber' | 'red' | 'gray';
export type TodoLinkKind = 'application' | 'meeting' | 'agenda_item' | 'ticket' | 'todo';

export interface TodoBoardSummary {
  id: Uuid;
  name: string;
  kind: TodoBoardKind;
  gremiumId: Uuid | null;
  canWrite: boolean;
  canConfigure: boolean;
  /** Not archived, not in the done column. */
  openCount: number;
}

export interface TodoColumn {
  id: Uuid;
  name: string;
  position: number;
  isDone: boolean;
  cardCount: number;
}

export interface TodoLabel {
  id: Uuid;
  name: string;
  color: TodoLabelColor;
}

/** The facts of a link target; only the fields of its kind are set. */
export interface TodoLinkDetail {
  stateLabel?: I18nMap | null;
  date?: string | null;
  meetingTitle?: string | null;
  position?: number | null;
  number?: string | null;
  status?: TicketStatus | null;
  boardName?: string | null;
  columnName?: string | null;
  isDone?: boolean | null;
}

export interface TodoLink {
  id: Uuid;
  kind: TodoLinkKind;
  targetId: Uuid;
  /** false: title, url and detail are null ("<Kind> (kein Zugriff)"). */
  accessible: boolean;
  title: string | null;
  url: string | null;
  detail: TodoLinkDetail | null;
}

export interface TodoCardTile {
  id: Uuid;
  boardId: Uuid;
  columnId: Uuid;
  rank: string;
  title: string;
  /** `YYYY-MM-DD`. */
  dueDate: string | null;
  completedAt: IsoDateTime | null;
  labelIds: Uuid[];
  assignees: PersonRef[];
  checklist: { done: number; total: number };
  commentCount: number;
  primaryLink: TodoLink | null;
  linkCount: number;
  version: number;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface TodoBoard {
  id: Uuid;
  name: string;
  kind: TodoBoardKind;
  gremiumId: Uuid | null;
  archiveAfterDays: number | null;
  canWrite: boolean;
  canConfigure: boolean;
  columns: TodoColumn[];
  labels: TodoLabel[];
  cards: TodoCardTile[];
  archivedCount: number;
}

export interface TodoCheckItem {
  id: Uuid;
  text: string;
  done: boolean;
  position: number;
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
  id: Uuid;
  kind: TodoEventKind;
  actor: PersonRef | null;
  at: IsoDateTime;
  payload: Record<string, unknown>;
}

export interface TodoComment {
  id: Uuid;
  author: PersonRef;
  body: string;
  mentions: PersonRef[];
  at: IsoDateTime;
  editedAt: IsoDateTime | null;
  isOwn: boolean;
  /** The files of the comment, oldest first. */
  attachments: MessageAttachment[];
}

export interface TodoCardDetail extends TodoCardTile {
  descriptionMd: string | null;
  boardName: string;
  boardKind: TodoBoardKind;
  canWrite: boolean;
  columns: { id: Uuid; name: string; isDone: boolean }[];
  labels: TodoLabel[];
  boardLabels: TodoLabel[];
  createdBy: PersonRef;
  links: TodoLink[];
  checklistItems: TodoCheckItem[];
  events: TodoEvent[];
  comments: TodoComment[];
  archivedAt: IsoDateTime | null;
}

export interface TodoCardCreate {
  boardId: Uuid;
  /** Default: the first column by position. */
  columnId?: Uuid;
  title: string;
  descriptionMd?: string | null;
  dueDate?: string | null;
  assigneeIds?: Uuid[];
  labelIds?: Uuid[];
  links?: { kind: TodoLinkKind; targetId: Uuid }[];
}

/** Content edits; `version` guards them (409 `card_version_conflict`). */
export interface TodoCardPatch {
  version: number;
  title?: string;
  descriptionMd?: string | null;
  dueDate?: string | null;
}

/** A move: `beforeId` places the card directly above that card, `afterId` directly
 *  below it; neither puts it at the end of the column. */
export interface TodoCardMove {
  columnId: Uuid;
  beforeId?: Uuid | null;
  afterId?: Uuid | null;
}

/**
 * A move to another board: into `columnId` (default: the first column), between
 * `afterId` (above) and `beforeId` (below) as in a move, else at the end.
 */
export interface TodoCardTransfer {
  boardId: Uuid;
  columnId?: Uuid | null;
  beforeId?: Uuid | null;
  afterId?: Uuid | null;
}

export interface TodoMineItem extends TodoCardTile {
  boardName: string;
  boardKind: TodoBoardKind;
  columnName: string;
  labels: TodoLabel[];
}

/** The open cards assigned to the caller over all boards. */
export interface TodoMine {
  items: TodoMineItem[];
  /** Cards due within 7 days, overdue included. */
  dueSoonCount: number;
}

/**
 * A board of `GET /todos/mine/boards` (the rows under "Meine To-Dos") or of
 * `GET /todos/all/boards` (the meta-board "Alle"): all its columns and labels, and its
 * live cards (done ones too): under "mine" only the ones assigned to the caller, under
 * "all" every one. `cardCount` of a column counts those cards.
 */
export interface TodoAssignedBoard {
  id: Uuid;
  name: string;
  kind: TodoBoardKind;
  gremiumId: Uuid | null;
  canWrite: boolean;
  columns: TodoColumn[];
  labels: TodoLabel[];
  cards: TodoCardTile[];
}

/** The answer of a poll of the rows: the boards and their ETag, or `boards: null` for 304. */
export interface TodoAssignedPoll {
  boards: TodoAssignedBoard[] | null;
  etag: string | null;
}

/** A hit of the link picker. */
export interface TodoLinkTarget {
  kind: TodoLinkKind;
  targetId: Uuid;
  title: string;
  detail: TodoLinkDetail;
}

/** The board settings a configurer may change. */
export interface TodoBoardPatch {
  name?: string;
  archiveAfterDays?: number | null;
}

/** The answer of a poll: a new board and its ETag, or `board: null` for 304. */
export interface TodoBoardPoll {
  board: TodoBoard | null;
  etag: string | null;
}

/** A card that links an application, a meeting, an agenda item or a ticket. */
export interface TodoLinkedCard {
  id: Uuid;
  boardId: Uuid;
  boardName: string;
  title: string;
  columnName: string;
  isDone: boolean;
  dueDate: string | null;
  assignees: PersonRef[];
}

/** An assignable person of a board; also the @-mention list. */
export interface TodoMember {
  principalId: Uuid;
  displayName: string | null;
}

@Injectable({ providedIn: 'root' })
export class TodosApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** The boards of the caller: personal, the gremium boards by name, team. */
  boards(gremiumId?: Uuid | null): Observable<TodoBoardSummary[]> {
    let params = new HttpParams();
    if (gremiumId) params = params.set('gremiumId', gremiumId);
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
    let headers = new HttpHeaders();
    if (etag) headers = headers.set('If-None-Match', etag);
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
    let params = new HttpParams();
    if (moveTo) params = params.set('moveTo', moveTo);
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
  archive(boardId: Uuid, q = '', offset = 0, limit = 50): Observable<Page<TodoCardTile>> {
    let params = new HttpParams().set('limit', limit).set('offset', offset);
    if (q) params = params.set('q', q);
    return this.http.get<Page<TodoCardTile>>(`${this.base}/todos/boards/${boardId}/archive`, {
      params,
      context: skipLoading(),
    });
  }

  members(boardId: Uuid): Observable<TodoMember[]> {
    return this.http.get<TodoMember[]>(`${this.base}/todos/boards/${boardId}/members`, {
      context: skipLoading(),
    });
  }

  createCard(body: TodoCardCreate): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(`${this.base}/todos/cards`, body);
  }

  card(cardId: Uuid): Observable<TodoCardDetail> {
    return this.http.get<TodoCardDetail>(`${this.base}/todos/cards/${cardId}`, { context: skipLoading() });
  }

  /** The tile of a live card, as the board read has it: what a live ping reads (404 when archived). */
  cardTile(cardId: Uuid): Observable<TodoCardTile> {
    return this.http.get<TodoCardTile>(`${this.base}/todos/cards/${cardId}/tile`, { context: skipLoading() });
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
    let headers = new HttpHeaders();
    if (etag) headers = headers.set('If-None-Match', etag);
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
    let params = new HttpParams().set('q', q).set('kind', kind);
    if (excludeCardId) params = params.set('excludeCardId', excludeCardId);
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
      context: skipLoading(),
    });
  }
}
