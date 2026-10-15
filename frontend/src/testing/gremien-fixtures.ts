/**
 * Test data of the tab "Gremien": a gremium of the overview, a member, a meeting, an
 * attendance matrix, the meetings of one person and a vote, plus a mock of the API that
 * answers with them.
 */
import { of } from 'rxjs';
import type {
  GremienApiService,
  GremiumAttendance,
  GremiumDecision,
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
    validFrom: '2025-10-01T00:00:00Z',
    validUntil: null,
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

export type GremienApiMock = { [K in keyof GremienApiService]: jest.Mock };

/** The API of the tab, answering with the data above. */
export function gremienApiMock(over: Partial<GremienApiMock> = {}): GremienApiMock {
  return {
    overview: jest.fn(() => of([gremium()])),
    members: jest.fn(() => of([member()])),
    meetings: jest.fn(() => of([gremiumMeeting()])),
    attendance: jest.fn(() => of(attendance())),
    memberAttendance: jest.fn(() => of(memberAttendance())),
    decisions: jest.fn(() => of({ items: [decision()], nextCursor: null })),
    ...over,
  };
}

/** The clock of the specs: Thursday, 15 October 2026. */
export const GREMIEN_TEST_NOW = (): Date => new Date(2026, 9, 15, 12, 0, 0);
