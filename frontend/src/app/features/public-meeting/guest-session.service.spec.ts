import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { WsService } from '@core/ws/ws.service';
import type { ClientMessage, ServerMessage } from '@core/ws/ws-messages';
import { guestMe, guestVote } from '../../../testing/guest-fixtures';
import { AltchaService } from '../apply/altcha.service';
import { GUEST_REFRESH_MS, GuestSessionService } from './guest-session.service';

const problem = (status: number, code?: string) =>
  new HttpErrorResponse({ status, error: code ? { code } : null });

class FakeChannel {
  readonly subject = new Subject<ServerMessage>();
  readonly messages$ = this.subject.asObservable();
  readonly sent: ClientMessage[] = [];
  closed = false;
  send(m: ClientMessage): void {
    this.sent.push(m);
  }
  close(): void {
    this.closed = true;
    this.subject.complete();
  }
}

describe('GuestSessionService', () => {
  let svc: GuestSessionService;
  let api: Record<string, jest.Mock>;
  let channels: FakeChannel[];
  let altcha: { solve: jest.Mock };

  function setup(mock = false) {
    channels = [];
    api = {
      publicMeeting: jest.fn(() => of(guestMe().meeting)),
      guestMe: jest.fn(() => of(guestMe())),
      joinPublicMeeting: jest.fn(() => of(guestMe({ status: 'pending', view: null }))),
      renameGuestMe: jest.fn(() => of(guestMe({ status: 'pending', displayName: 'Neu', view: null }))),
      leavePublicMeeting: jest.fn(() => of(undefined)),
    };
    altcha = { solve: jest.fn(() => Promise.resolve('solution')) };
    TestBed.configureTestingModule({
      providers: [
        GuestSessionService,
        { provide: ApiClient, useValue: api },
        { provide: AltchaService, useValue: altcha },
        { provide: USE_MOCK_API, useValue: mock },
        {
          provide: WsService,
          useValue: {
            connectGuest: jest.fn(() => {
              const ch = new FakeChannel();
              channels.push(ch);
              return ch;
            }),
          },
        },
      ],
    });
    svc = TestBed.inject(GuestSessionService);
  }

  afterEach(() => {
    jest.useRealTimers();
    TestBed.resetTestingModule();
  });

  it('loads the head and the own state, then follows the guest channel', () => {
    setup();
    expect(svc.state()).toBe('loading');
    svc.load('7KQ4MP');
    expect(svc.state()).toBe('admitted');
    expect(channels).toHaveLength(1);
    expect(channels[0].sent).toEqual([{ type: 'subscribe' }]);
    // The same state again keeps the one channel.
    svc.refresh();
    expect(channels).toHaveLength(1);
  });

  it('reads the state again shortly after live events, once per burst', () => {
    jest.useFakeTimers();
    setup();
    svc.load('7KQ4MP');
    api['guestMe'].mockClear();
    channels[0].subject.next({ type: 'vote_opened', voteId: 'v', options: [], closesAt: null });
    channels[0].subject.next({ type: 'guest_counts', admittedGuests: 8 });
    channels[0].subject.next({ type: 'error', code: 'x' });
    jest.advanceTimersByTime(GUEST_REFRESH_MS);
    expect(api['guestMe']).toHaveBeenCalledTimes(1);
  });

  it('shows "nicht mehr öffentlich" when the lead switches the participation off', () => {
    jest.useFakeTimers();
    setup();
    svc.load('7KQ4MP');
    api['guestMe'].mockReturnValue(throwError(() => problem(404, 'meeting_not_public')));
    channels[0].subject.next({
      type: 'guest_status',
      status: 'removed',
      displayName: null,
      number: 1,
      reason: 'public_off',
    });
    expect(svc.state()).toBe('notPublic');
    jest.advanceTimersByTime(GUEST_REFRESH_MS);
    expect(svc.state()).toBe('notPublic');
    expect(channels[0].closed).toBe(true);
  });

  it('reconnects a dropped channel while the guest takes part, and gives up later', () => {
    jest.useFakeTimers();
    setup();
    svc.load('7KQ4MP');
    for (let i = 1; i <= 6; i++) {
      channels[channels.length - 1].subject.complete();
      jest.advanceTimersByTime(60_000);
    }
    expect(channels).toHaveLength(6);
  });

  it('does not reconnect a channel it dropped itself', () => {
    jest.useFakeTimers();
    setup();
    svc.load('7KQ4MP');
    svc.leave();
    jest.advanceTimersByTime(60_000);
    expect(channels).toHaveLength(1);
    expect(svc.state()).toBe('join');
  });

  it('opens no channel in mock mode', () => {
    setup(true);
    svc.load('7KQ4MP');
    expect(channels).toHaveLength(0);
  });

  it('maps the failures of the head: unknown code, not public, other errors', () => {
    setup();
    api['publicMeeting'].mockReturnValue(throwError(() => problem(404, 'join_code_unknown')));
    svc.load('X');
    expect(svc.state()).toBe('unknown');
    api['publicMeeting'].mockReturnValue(throwError(() => problem(404)));
    svc.load('X');
    expect(svc.state()).toBe('unknown');
    api['publicMeeting'].mockReturnValue(throwError(() => problem(404, 'meeting_not_public')));
    svc.load('X');
    expect(svc.state()).toBe('notPublic');
    api['publicMeeting'].mockReturnValue(throwError(() => new Error('offline')));
    svc.load('X');
    expect(svc.state()).toBe('error');
  });

  it('gives the join form to a device without a request', () => {
    setup();
    api['guestMe'].mockReturnValue(throwError(() => problem(401, 'guest_token_missing')));
    svc.load('7KQ4MP');
    expect(svc.state()).toBe('join');
    api['guestMe'].mockReturnValue(throwError(() => problem(404, 'guest_not_found')));
    svc.load('7KQ4MP');
    expect(svc.state()).toBe('join');
    // A first read without a code keeps the form; a later one reports the error.
    api['guestMe'].mockReturnValue(throwError(() => problem(500)));
    svc.load('7KQ4MP');
    expect(svc.state()).toBe('join');
    svc.refresh();
    expect(svc.state()).toBe('error');
  });

  it('shows "closed" for a closed meeting and treats a left guest as new', () => {
    setup();
    api['guestMe'].mockReturnValue(of(guestMe({ status: 'left', view: null })));
    svc.load('7KQ4MP');
    expect(svc.state()).toBe('join');
    api['guestMe'].mockReturnValue(
      of(guestMe({ meeting: { ...guestMe().meeting, status: 'closed' } })),
    );
    svc.refresh();
    expect(svc.state()).toBe('closed');
  });

  it('joins with ALTCHA and keeps short names out', async () => {
    setup();
    api['guestMe'].mockReturnValue(throwError(() => problem(401)));
    svc.load('7KQ4MP');
    await svc.join('J');
    expect(api['joinPublicMeeting']).not.toHaveBeenCalled();
    await svc.join(' Jana Roth ');
    expect(api['joinPublicMeeting']).toHaveBeenCalledWith('7KQ4MP', 'Jana Roth', 'solution');
    expect(svc.state()).toBe('pending');
  });

  it('remembers a guest admitted while a vote runs', () => {
    setup();
    api['guestMe'].mockReturnValue(of(guestMe({ status: 'pending', view: null })));
    svc.load('7KQ4MP');
    api['guestMe'].mockReturnValue(of(guestMe()));
    svc.refresh();
    expect(svc.admittedDuringVote()).toBe(true);
    api['guestMe'].mockReturnValue(of(guestMe({ view: { ...guestMe().view!, votes: [guestVote({ status: 'closed' })] } })));
    svc.refresh();
    expect(svc.admittedDuringVote()).toBe(false);
  });

  it('reports a failed ALTCHA and the refusals of the join', async () => {
    setup();
    svc.load('7KQ4MP');
    altcha.solve.mockReturnValueOnce(Promise.reject(new Error('x')));
    await svc.join('Jana Roth');
    expect(svc.joinError()).toBe('altcha_failed');

    api['joinPublicMeeting'].mockReturnValue(throwError(() => problem(400, 'altcha_failed')));
    await svc.join('Jana Roth');
    expect(svc.joinError()).toBe('altcha_failed');
    api['joinPublicMeeting'].mockReturnValue(throwError(() => problem(429)));
    await svc.join('Jana Roth');
    expect(svc.joinError()).toBe('rate_limited');
    api['joinPublicMeeting'].mockReturnValue(throwError(() => new Error('offline')));
    await svc.join('Jana Roth');
    expect(svc.joinError()).toBe('error');

    api['guestMe'].mockClear();
    api['joinPublicMeeting'].mockReturnValue(throwError(() => problem(429, 'retry_later')));
    await svc.join('Jana Roth');
    expect(api['guestMe']).toHaveBeenCalled();
    api['publicMeeting'].mockClear();
    api['joinPublicMeeting'].mockReturnValue(throwError(() => problem(409, 'meeting_closed')));
    await svc.join('Jana Roth');
    expect(api['publicMeeting']).toHaveBeenCalled();
  });

  it('ignores a second join while one runs', async () => {
    setup();
    svc.load('7KQ4MP');
    api['joinPublicMeeting'].mockReturnValue({ subscribe: () => {} });
    await svc.join('Jana Roth');
    await svc.join('Jana Roth');
    expect(api['joinPublicMeeting']).toHaveBeenCalledTimes(1);
  });

  it('renames a request and reads the state again after a refused write', () => {
    setup();
    svc.load('7KQ4MP');
    svc.rename('X');
    expect(api['renameGuestMe']).not.toHaveBeenCalled();
    svc.rename('Neu');
    expect(svc.me()?.displayName).toBe('Neu');
    api['renameGuestMe'].mockReturnValue(throwError(() => problem(409, 'guest_not_pending')));
    api['guestMe'].mockClear();
    svc.rename('Neuer');
    expect(api['guestMe']).toHaveBeenCalled();
    api['leavePublicMeeting'].mockReturnValue(throwError(() => problem(500)));
    svc.leave();
    expect(svc.saving()).toBe(false);
    api['renameGuestMe'].mockReturnValue({ subscribe: () => {} });
    svc.rename('Langsam');
    svc.rename('Langsam 2');
    svc.leave();
    expect(api['renameGuestMe']).toHaveBeenCalledTimes(3);
  });

  it('closes the channel on destroy and for a final state', () => {
    setup();
    svc.load('7KQ4MP');
    api['guestMe'].mockReturnValue(of(guestMe({ status: 'rejected', retryAfter: 180, view: null })));
    svc.refresh();
    expect(channels[0].closed).toBe(true);
    expect(svc.state()).toBe('rejected');
    svc.ngOnDestroy();
  });

  it('drops a pending reconnect on leave and a pending read on destroy', () => {
    jest.useFakeTimers();
    setup();
    svc.load('7KQ4MP');
    channels[0].subject.complete();
    svc.leave();
    jest.advanceTimersByTime(60_000);
    expect(channels).toHaveLength(1);
    svc.load('7KQ4MP');
    channels[1].subject.next({ type: 'guest_counts', admittedGuests: 1 });
    api['guestMe'].mockClear();
    svc.ngOnDestroy();
    jest.advanceTimersByTime(GUEST_REFRESH_MS);
    expect(api['guestMe']).not.toHaveBeenCalled();
  });

  it('does not reconnect after the request ended or the page closed', () => {
    jest.useFakeTimers();
    setup();
    api['guestMe'].mockReturnValue(of(guestMe({ status: 'pending', view: null })));
    svc.load('7KQ4MP');
    svc.me.set(guestMe({ status: 'rejected', view: null }));
    channels[0].subject.complete();
    jest.advanceTimersByTime(60_000);
    expect(channels).toHaveLength(1);
  });
});
