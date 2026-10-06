import type { GuestMe, JoinLink, MeetingGuest } from './models';
import {
  MOCK_JOIN_CODE,
  type MockReply,
  mockGuestCounts,
  mockJoinLink,
  mockLeadGuests,
  mockPublicMeeting,
} from './mock-public-meeting';

const body = <T>(r: MockReply | null): T => (r as { body: T }).body;
const code = (r: MockReply | null): string => (r as { problem: { code: string } }).problem.code;
const M = '/api/meetings/m-1';

describe('mock public meeting (#17)', () => {
  it('serves the lead: guests, link, decisions, rename, admit-all and rotation', () => {
    const guests = body<MeetingGuest[]>(mockLeadGuests('GET', `${M}/guests`, null));
    expect(guests).toHaveLength(10);
    expect(mockGuestCounts()).toEqual({ pending: 3, admitted: 7 });
    expect(body<JoinLink>(mockLeadGuests('GET', `${M}/join-link`, null)).joinCode).toBe(MOCK_JOIN_CODE);
    const pending = guests.filter((g) => g.status === 'pending');
    expect(body<MeetingGuest>(mockLeadGuests('POST', `${M}/guests/${pending[0].id}/admit`, null)).status).toBe('admitted');
    expect(code(mockLeadGuests('POST', `${M}/guests/${pending[0].id}/reject`, null))).toBe('guest_not_pending');
    expect(body<MeetingGuest>(mockLeadGuests('POST', `${M}/guests/${pending[1].id}/reject`, null)).status).toBe('rejected');
    expect(code(mockLeadGuests('POST', `${M}/guests/${pending[1].id}/remove`, null))).toBe('guest_not_admitted');
    expect(body<MeetingGuest>(mockLeadGuests('POST', `${M}/guests/${pending[0].id}/remove`, null)).status).toBe('removed');
    expect(body<MeetingGuest>(mockLeadGuests('POST', `${M}/guests/${guests[0].id}/rename`, { displayName: ' Neu ' })).displayName).toBe('Neu');
    expect(body<MeetingGuest>(mockLeadGuests('POST', `${M}/guests/${guests[0].id}/rename`, null)).displayName).toBe('Neu');
    expect(code(mockLeadGuests('POST', `${M}/guests/zzz/admit`, null))).toBe('not_found');
    expect(body<MeetingGuest[]>(mockLeadGuests('POST', `${M}/guests/admit-all`, null))).toHaveLength(1);
    expect(body<JoinLink>(mockLeadGuests('POST', `${M}/join-code/rotate`, null)).joinCode).toBe('9XH2TR');
    expect(mockLeadGuests('DELETE', `${M}/guests`, null)).toBeNull();
    expect(mockJoinLink().qr.rows).toHaveLength(33);
  });

  it('serves every state of the join page by its code', () => {
    const me = (c: string) => mockPublicMeeting('GET', `/api/public/meetings/${c}/me`, null);
    expect(body<GuestMe>(me(MOCK_JOIN_CODE)).view?.votes[0].canCast).toBe(true);
    expect(body<GuestMe>(me('MOCKNOVOTE')).view?.votes).toEqual([]);
    expect(body<GuestMe>(me('MOCKSECRET')).view?.votes[0].secret).toBe(true);
    expect(body<GuestMe>(me('MOCKMEMBERS')).view?.votes[0].guestsVote).toBe(false);
    expect(body<GuestMe>(me('MOCKWATCH')).meeting.guestsMode).toBe('watch');
    expect(code(me('MOCKJOIN'))).toBe('guest_token_missing');
    expect(body<GuestMe>(me('MOCKWAIT')).status).toBe('pending');
    expect(body<GuestMe>(me('MOCKREJECT')).retryAfter).toBe(150);
    expect(code(me('MOCKOFF'))).toBe('meeting_not_public');
    expect(code(mockPublicMeeting('GET', '/api/public/meetings/NOPE', null))).toBe('join_code_unknown');
    expect(body<{ status: string }>(mockPublicMeeting('GET', '/api/public/meetings/MOCKCLOSED', null)).status).toBe('closed');
    expect(mockPublicMeeting('POST', '/api/public/meetings/MOCKCLOSED', null)).toBeNull();
    expect(mockPublicMeeting('GET', '/api/other', null)).toBeNull();
  });

  it('joins, renames, casts and leaves', () => {
    const c = 'MOCKJOIN';
    expect(code(mockPublicMeeting('POST', '/api/public/meetings/join/MOCKOFF', {}))).toBe('meeting_not_public');
    expect(body<GuestMe>(mockPublicMeeting('POST', `/api/public/meetings/join/${c}`, { displayName: 'Ali' })).status).toBe('pending');
    expect(body<GuestMe>(mockPublicMeeting('POST', `/api/public/meetings/join/${c}`, null)).displayName).toBe('');
    expect(body<GuestMe>(mockPublicMeeting('PATCH', `/api/public/meetings/${c}/me`, { displayName: 'Alina' })).displayName).toBe('Alina');
    expect(body<GuestMe>(mockPublicMeeting('PATCH', `/api/public/meetings/${c}/me`, null)).displayName).toBe('Alina');
    expect(mockPublicMeeting('PUT', `/api/public/meetings/${c}/me`, null)).toBeNull();
    expect(code(mockPublicMeeting('POST', `/api/public/meetings/${c}/votes/pv-3/ballot`, {}))).toBe('guest_not_admitted');
    expect(mockPublicMeeting('DELETE', `/api/public/meetings/${c}/me`, null)?.status).toBe(204);

    const cast = mockPublicMeeting('POST', `/api/public/meetings/${MOCK_JOIN_CODE}/votes/pv-3/ballot`, { choice: 'yes' });
    expect(body<{ status: string }>(cast).status).toBe('cast');
    const v = body<GuestMe>(mockPublicMeeting('GET', `/api/public/meetings/${MOCK_JOIN_CODE}/me`, null)).view!.votes[0];
    expect(v.myBallot).toEqual({ cast: true, choice: 'yes' });
    mockPublicMeeting('POST', '/api/public/meetings/MOCKSECRET/votes/pv-5/ballot', null);
    const s = body<GuestMe>(mockPublicMeeting('GET', '/api/public/meetings/MOCKSECRET/me', null)).view!.votes[0];
    expect(s.myBallot).toEqual({ cast: true, choice: null });
  });
});
