/**
 * Test data of the to-do specs: a gremium board with four columns (the last is done), two
 * labels and three cards, a card detail and the board list.
 */
import type { Provider } from '@angular/core';
import { of } from 'rxjs';
import {
  TodosApiService,
  type TodoBoard,
  type TodoBoardSummary,
  type TodoCardDetail,
  type TodoCardTile,
  type TodoLink,
  type TodoMember,
} from '../app/core/api/todos.service';

export const TODAY = '2026-10-16';

/** A to-do API without linked cards, for pages that show the back-references "To-Dos". */
export const NO_LINKED_TODOS: Provider = { provide: TodosApiService, useValue: { linked: () => of([]) } };

export function link(over: Partial<TodoLink> = {}): TodoLink {
  return {
    id: 'li-1',
    kind: 'application',
    targetId: 'a-1',
    accessible: true,
    title: 'Lerncafé',
    url: '/applications/a-1',
    detail: null,
    ...over,
  };
}

export function tile(over: Partial<TodoCardTile> = {}): TodoCardTile {
  return {
    id: 'k-1',
    boardId: 'b-1',
    columnId: 'c-1',
    rank: 'a',
    title: 'Protokoll gegenlesen',
    dueDate: null,
    completedAt: null,
    labelIds: [],
    assignees: [],
    checklist: { done: 0, total: 0 },
    commentCount: 0,
    primaryLink: null,
    linkCount: 0,
    version: 1,
    createdAt: '2026-10-01T10:00:00Z',
    updatedAt: '2026-10-01T10:00:00Z',
    ...over,
  };
}

export function board(over: Partial<TodoBoard> = {}): TodoBoard {
  const cards = over.cards ?? [
    tile({ id: 'k-1', columnId: 'c-1', title: 'Raum buchen' }),
    tile({ id: 'k-2', columnId: 'c-1', title: 'Haushalt Kapitel 3', labelIds: ['l-1'] }),
    tile({ id: 'k-3', columnId: 'c-4', title: 'Bus anfragen', completedAt: '2026-10-10T10:00:00Z' }),
  ];
  const columns = (over.columns ?? [
    { id: 'c-1', name: 'Offen', position: 0, isDone: false, cardCount: 0 },
    { id: 'c-2', name: 'In Arbeit', position: 1, isDone: false, cardCount: 0 },
    { id: 'c-3', name: 'Wartet', position: 2, isDone: false, cardCount: 0 },
    { id: 'c-4', name: 'Erledigt', position: 3, isDone: true, cardCount: 0 },
  ]).map((c) => ({ ...c, cardCount: cards.filter((k) => k.columnId === c.id).length }));
  return {
    id: 'b-1',
    name: 'Studierendenparlament',
    kind: 'gremium',
    gremiumId: 'g-1',
    archiveAfterDays: 30,
    canWrite: true,
    canConfigure: true,
    labels: [
      { id: 'l-1', name: 'Haushalt', color: 'amber' },
      { id: 'l-2', name: 'Sitzung', color: 'blue' },
    ],
    archivedCount: 0,
    ...over,
    columns,
    cards,
  };
}

export function summary(over: Partial<TodoBoardSummary> = {}): TodoBoardSummary {
  return {
    id: 'b-1',
    name: 'Studierendenparlament',
    kind: 'gremium',
    gremiumId: 'g-1',
    canWrite: true,
    canConfigure: true,
    openCount: 2,
    ...over,
  };
}

export const BOARDS: TodoBoardSummary[] = [
  summary({ id: 'b-0', name: 'Meine To-Dos', kind: 'personal', gremiumId: null, canConfigure: true, openCount: 1 }),
  summary(),
  summary({ id: 'b-2', name: 'Fachschaft Informatik', gremiumId: 'g-2', canConfigure: false, openCount: 4 }),
  summary({ id: 'b-3', name: 'Tickets', kind: 'team', gremiumId: null, canConfigure: false, openCount: 6 }),
];

export const MEMBERS: TodoMember[] = [
  { principalId: 'p-1', displayName: 'Selin Yıldız' },
  { principalId: 'p-2', displayName: 'Jonas Weber' },
  { principalId: 'p-3', displayName: null },
];

export function detail(over: Partial<TodoCardDetail> = {}): TodoCardDetail {
  return {
    ...tile({ id: 'k-1', title: 'Raum buchen', dueDate: '2026-10-23' }),
    descriptionMd: 'Raum **A 101**',
    boardName: 'Studierendenparlament',
    boardKind: 'gremium',
    canWrite: true,
    columns: [
      { id: 'c-1', name: 'Offen', isDone: false },
      { id: 'c-2', name: 'In Arbeit', isDone: false },
      { id: 'c-4', name: 'Erledigt', isDone: true },
    ],
    labels: [{ id: 'l-1', name: 'Haushalt', color: 'amber' }],
    boardLabels: [
      { id: 'l-1', name: 'Haushalt', color: 'amber' },
      { id: 'l-2', name: 'Sitzung', color: 'blue' },
    ],
    createdBy: { principalId: 'p-1', displayName: 'Selin Yıldız' },
    links: [link()],
    checklistItems: [
      { id: 'i-1', text: 'Termin klären', done: true, position: 0 },
      { id: 'i-2', text: 'Raum anfragen', done: false, position: 1 },
    ],
    events: [],
    comments: [],
    archivedAt: null,
    ...over,
  };
}

/** Let `mediaQuerySignal(MEDIA.phone)` match (restore with `jest.restoreAllMocks()`). */
export function asPhone(phoneQuery: string): void {
  jest.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: query === phoneQuery,
        media: query,
        onchange: null,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      }) as MediaQueryList,
  );
}
