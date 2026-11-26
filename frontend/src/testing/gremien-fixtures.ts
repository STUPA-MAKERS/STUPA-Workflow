/**
 * Test data of the tab "Gremien": a gremium of the overview, a member, a meeting, an
 * attendance matrix, the meetings of one person and a vote, plus a mock of the API that
 * answers with them.
 */
import { map, type Observable, of } from 'rxjs';
import type { Team, TeamsApiService } from '../app/core/api/teams.service';
import type {
  GremienApiService,
  GremiumAttendance,
  GremiumDecision,
  GremiumInfo,
  GremiumMeeting,
  GremiumMember,
  GremiumMemberAttendance,
  GremiumOverview,
} from '../app/core/api/gremien.service';

export function gremium(over: Partial<GremiumOverview> = {}): GremiumOverview {
  return {
    id: 'g-1',
    name: 'Studierendenparlament',
    slug: 'stupa',
    isMember: true,
    roleKey: 'member',
    roleName: { de: 'Mitglied', en: 'Member' },
    memberCount: 31,
    nextMeeting: { id: 'm-9', title: '34. Sitzung', date: '2026-10-20', startTime: '18:00:00', status: 'planned' },
    live: false,
    quorumPercent: 50,
    protocolsPublic: true,
    allowVoteDelegation: true,
    logoUrl: null,
    ...over,
  };
}

export function member(over: Partial<GremiumMember> = {}): GremiumMember {
  return {
    principalId: 'p-1',
    displayName: 'Finn Schulze',
    email: 'finn.schulze@example.org',
    roleId: 'r-member',
    roleKey: 'member',
    roleName: { de: 'Mitglied', en: 'Member' },
    isSelf: false,
    ...over,
  };
}

export function gremiumMeeting(over: Partial<GremiumMeeting> = {}): GremiumMeeting {
  return {
    id: 'm-1',
    title: '33. Sitzung',
    date: '2026-10-06',
    startTime: '18:00:00',
    endTime: '20:30:00',
    status: 'closed',
    agendaItemCount: 7,
    presentCount: 24,
    memberCount: 31,
    protocolStatus: 'final',
    ...over,
  };
}

/** Two months (September with two meetings, October with none) and three people. */
export function attendance(over: Partial<GremiumAttendance> = {}): GremiumAttendance {
  return {
    fromMonth: '2026-09',
    toMonth: '2026-10',
    termStart: '2026-10-01',
    terms: ['2026-10-01', '2025-10-01'],
    absenceLimit: 3,
    months: [
      { month: '2026-09', meetings: 2 },
      { month: '2026-10', meetings: 0 },
    ],
    rows: [
      {
        principalId: 'p-1',
        displayName: 'Finn Schulze',
        roleKey: 'member',
        roleName: { de: 'Mitglied', en: 'Member' },
        isSelf: false,
        unexcused: 2,
        cells: [
          { month: '2026-09', member: true, present: 1, excused: 1, delegated: 1 },
          { month: '2026-10', member: true, present: 0, excused: 0, delegated: 0 },
        ],
      },
      {
        principalId: 'p-2',
        displayName: 'Anna Berg',
        roleKey: 'vorstand',
        roleName: { de: 'Vorstand', en: 'Board' },
        isSelf: true,
        unexcused: 0,
        cells: [
          { month: '2026-09', member: true, present: 2, excused: 0, delegated: 0 },
          { month: '2026-10', member: true, present: 0, excused: 0, delegated: 0 },
        ],
      },
      {
        principalId: 'p-3',
        displayName: 'Kai Meier',
        roleKey: 'member',
        roleName: { de: 'Mitglied', en: 'Member' },
        isSelf: false,
        unexcused: 0,
        cells: [
          { month: '2026-09', member: false, present: 0, excused: 0, delegated: 0 },
          { month: '2026-10', member: true, present: 0, excused: 0, delegated: 0 },
        ],
      },
    ],
    ...over,
  };
}

export function memberAttendance(over: Partial<GremiumMemberAttendance> = {}): GremiumMemberAttendance {
  return {
    principalId: 'p-1',
    displayName: 'Finn Schulze',
    month: '2026-09',
    meetings: [
      { meetingId: 'm-2', title: '32. Sitzung', date: '2026-09-29', startTime: '18:00:00', status: 'excused', delegateName: null },
      { meetingId: 'm-3', title: '31. Sitzung', date: '2026-09-15', startTime: '18:00:00', status: 'delegated', delegateName: 'Kai Meier' },
    ],
    ...over,
  };
}

export function decision(over: Partial<GremiumDecision> = {}): GremiumDecision {
  return {
    id: 'v-1',
    question: 'Lastenrad für das Fachschaftsbüro',
    kind: 'application',
    applicationId: 'a-1',
    applicationTitle: 'Lastenrad',
    amount: '2890.00',
    secret: false,
    majorityRule: 'simple',
    counts: { yes: 19, no: 4, abstain: 2 },
    ballots: 25,
    result: 'passed',
    elected: [],
    meetingId: 'm-1',
    meetingTitle: '33. Sitzung',
    meetingDate: '2026-10-06',
    closedAt: '2026-10-06T19:12:00Z',
    ...over,
  };
}

/** The Info of a gremium; the default is empty and not editable, so the tab hides. */
export function gremiumInfo(over: Partial<GremiumInfo> = {}): GremiumInfo {
  return {
    bodyMd: '',
    links: [],
    version: 0,
    updatedAt: null,
    updatedByName: null,
    canEdit: false,
    ...over,
  };
}

export type GremienApiMock = { [K in keyof GremienApiService]: jest.Mock };

/** The API of the tab, answering with the data above. */
export function gremienApiMock(over: Partial<GremienApiMock> = {}): GremienApiMock {
  return {
    overview: jest.fn(() => of([gremium()])),
    members: jest.fn(() => of([member()])),
    meetings: jest.fn(() => of([gremiumMeeting()])),
    attendance: jest.fn(() => of(attendance())),
    attendanceExport: jest.fn(() => of(new Blob(['x']))),
    memberAttendance: jest.fn(() => of(memberAttendance())),
    decisions: jest.fn(() => of({ items: [decision()], nextCursor: null })),
    info: jest.fn(() => of(gremiumInfo())),
    saveInfo: jest.fn(() => of(gremiumInfo({ version: 1, canEdit: true }))),
    notify: jest.fn(() => of({ recipients: 3 })),
    ...over,
  };
}

/** The clock of the specs: Thursday, 15 October 2026. */
export const GREMIEN_TEST_NOW = (): Date => new Date(2026, 9, 15, 12, 0, 0);

/** The inherent team of a Gremium row, with the id of the Gremium, so a spec opens `/teams/g-1`. */
export function teamOfGremium(g: GremiumOverview, over: Partial<Team> = {}): Team {
  return {
    id: g.id,
    name: g.name,
    gremiumId: g.id,
    parentId: null,
    parentName: null,
    boardId: null,
    isMember: g.isMember,
    canManage: false,
    ...over,
  };
}

/** A free team (spec 003063). */
export function freeTeam(over: Partial<Team> = {}): Team {
  return {
    id: 't-1',
    name: 'Ersti-Woche',
    gremiumId: null,
    parentId: null,
    parentName: null,
    boardId: 'b-t1',
    isMember: true,
    canManage: true,
    ...over,
  };
}

/**
 * The team API of the tab: the list follows the overview of `gremien` (one inherent team per
 * Gremium, same id), plus `extra` teams.
 */
export function teamsApiMock(
  gremien: Pick<GremienApiMock, 'overview'>,
  extra: readonly Team[] = [],
): { [K in keyof TeamsApiService]: jest.Mock } {
  return {
    list: jest.fn(() =>
      ((gremien.overview.getMockImplementation() ?? gremien.overview)() as Observable<
        readonly GremiumOverview[]
      >).pipe(
        map((rows) => [...rows.map((g) => teamOfGremium(g)), ...extra]),
      ),
    ),
    detail: jest.fn((id: string) =>
      of({ team: extra.find((t) => t.id === id) ?? freeTeam({ id }), members: [], subTeams: [] }),
    ),
    create: jest.fn((name: string, parentId: string | null) =>
      of({ team: freeTeam({ id: 't-new', name, parentId }), members: [], subTeams: [] }),
    ),
    patch: jest.fn(() => of({ team: freeTeam(), members: [], subTeams: [] })),
    remove: jest.fn(() => of(undefined)),
    setMember: jest.fn(() => of({ team: freeTeam(), members: [], subTeams: [] })),
    removeMember: jest.fn(() => of({ team: freeTeam(), members: [], subTeams: [] })),
  };
}

