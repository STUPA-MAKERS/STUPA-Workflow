/**
 * API of the to-dos (`/api/todos`): boards, cards and their links.
 *
 * A board is a gremium board (members with `todo.write`), a personal board (the owner)
 * or a team board (holders of its permission). A board or a card the caller may not read
 * answers 404. The client only binds the data; the server stays authoritative.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { I18nMap, IsoDateTime, PersonRef, Uuid } from '@core/api/models';
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

  members(boardId: Uuid): Observable<TodoMember[]> {
    return this.http.get<TodoMember[]>(`${this.base}/todos/boards/${boardId}/members`, {
      context: skipLoading(),
    });
  }

  createCard(body: TodoCardCreate): Observable<TodoCardDetail> {
    return this.http.post<TodoCardDetail>(`${this.base}/todos/cards`, body);
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
