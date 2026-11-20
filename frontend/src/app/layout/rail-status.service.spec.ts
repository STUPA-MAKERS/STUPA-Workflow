import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { Subject } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Principal } from '@core/api/models';
import type { NavigationStatus } from '@core/api/activity.service';
import { AuthService } from '@core/auth/auth.service';
import { cacheInterceptor } from '@core/cache/cache.interceptor';
import { SKIP_LOADING } from '@stupa-makers/ui-kit';
import type { MeetingStateMsg } from '@core/ws/ws-messages';
import { WsService } from '@core/ws/ws.service';
import { createLocationMock, provideLocationMock } from '../../testing/location-mock';
import {
  RAIL_STATUS_DEBOUNCE_MS,
  RAIL_STATUS_POLL_MS,
  RAIL_STATUS_WRITE_DEBOUNCE_MS,
  RailStatusService,
} from './rail-status.service';

@Component({ changeDetection: ChangeDetectionStrategy.Eager, standalone: true, template: '' })
class StubPage {}

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: [],
  groups: [],
  gremien: [{ id: 'g1', name: 'StuPa', slug: 'stupa' }],
};

const STATUS = '/api/navigation/status';

const marks = (over: Partial<NavigationStatus> = {}): NavigationStatus => ({
  tasks: 3,
  tickets: null,
  live: false,
  activity: false,
  ...over,
});

function setup() {
  const states = new Subject<MeetingStateMsg>();
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        { path: 'a', component: StubPage },
        { path: 'b', component: StubPage },
      ]),
      provideHttpClient(withInterceptors([cacheInterceptor])),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideLocationMock(createLocationMock()),
      { provide: WsService, useValue: { meetingStates$: states.asObservable() } },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const auth = TestBed.inject(AuthService);
  const svc = TestBed.inject(RailStatusService);
  const router = TestBed.inject(Router);
  return { http, auth, svc, router, states, client: TestBed.inject(HttpClient) };
}

type Env = ReturnType<typeof setup>;

/** Sign in, let the first read go out and answer it. */
function signIn(env: Env, answer: NavigationStatus = marks()): void {
  env.auth.ensureLoaded().subscribe();
  env.http.expectOne('/api/auth/me').flush(MEMBER);
  TestBed.tick();
  jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
  env.http.expectOne(STATUS).flush(answer);
}

const state = (status: string): MeetingStateMsg => ({ type: 'meeting_state', status }) as unknown as MeetingStateMsg;

describe('RailStatusService', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('asks nothing and shows no marks while nobody is signed in', () => {
    const env = setup();
    jest.advanceTimersByTime(RAIL_STATUS_POLL_MS * 2);
    env.http.expectNone(STATUS);
    expect(env.svc.taskCount()).toBeNull();
    expect(env.svc.live()).toBe(false);
  });

  it('reads all four marks in one request at sign-in, without the loading bar', () => {
    const env = setup();
    env.auth.ensureLoaded().subscribe();
    env.http.expectOne('/api/auth/me').flush(MEMBER);
    TestBed.tick();
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    const read = env.http.expectOne(STATUS);
    expect(read.request.context.get(SKIP_LOADING)).toBe(true);
    read.flush(marks({ tasks: 4, tickets: 2, live: true, activity: true }));
    expect(env.svc.taskCount()).toBe(4);
    expect(env.svc.ticketCount()).toBe(2);
    expect(env.svc.live()).toBe(true);
    expect(env.svc.activityNew()).toBe(true);
    env.http.verify();
  });

  it('does not read again on a navigation', async () => {
    const env = setup();
    signIn(env);
    await env.router.navigateByUrl('/a');
    await env.router.navigateByUrl('/b');
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS * 2);
    env.http.expectNone(STATUS);
  });

  it('reads again once after a burst of writes, but not after its own mark of the activity page', () => {
    const env = setup();
    signIn(env);
    env.client.post('/api/activity/seen', {}).subscribe();
    env.http.expectOne('/api/activity/seen').flush(null);
    jest.advanceTimersByTime(RAIL_STATUS_WRITE_DEBOUNCE_MS + RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectNone(STATUS);

    for (const id of ['x', 'y']) {
      env.client.post(`/api/applications/${id}/transitions`, {}).subscribe();
      env.http.expectOne(`/api/applications/${id}/transitions`).flush({});
    }
    jest.advanceTimersByTime(RAIL_STATUS_WRITE_DEBOUNCE_MS + RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectOne(STATUS).flush(marks({ tasks: 1 }));
    expect(env.svc.taskCount()).toBe(1);
  });

  it('reads again when a meeting changes its status, not on another frame of the same status', () => {
    const env = setup();
    signIn(env);
    env.states.next(state('live'));
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectOne(STATUS).flush(marks({ live: true }));
    env.states.next(state('live'));
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectNone(STATUS);
    expect(env.svc.live()).toBe(true);
  });

  it('polls while the tab is visible, skips the poll while hidden, and reads on the return', () => {
    const env = setup();
    signIn(env);
    jest.advanceTimersByTime(RAIL_STATUS_POLL_MS + RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectOne(STATUS).flush(marks());

    const visibility = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    jest.advanceTimersByTime(RAIL_STATUS_POLL_MS + RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectNone(STATUS);
    visibility.mockReturnValue('visible');
    document.dispatchEvent(new Event('visibilitychange'));
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectOne(STATUS).flush(marks());
    visibility.mockRestore();
  });

  it('clears the marks on a failed read and at sign-out', () => {
    const env = setup();
    signIn(env, marks({ tasks: 3, tickets: 1, live: true, activity: true }));
    env.svc.refresh();
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectOne(STATUS).flush(null, { status: 500, statusText: 'x' });
    expect(env.svc.taskCount()).toBeNull();
    expect(env.svc.ticketCount()).toBeNull();
    expect(env.svc.live()).toBe(false);

    env.svc.refresh();
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectOne(STATUS).flush(marks({ activity: true }));
    expect(env.svc.taskCount()).toBe(3);
    env.svc.activitySeen();
    expect(env.svc.activityNew()).toBe(false);

    env.auth.handleUnauthorized();
    TestBed.tick();
    expect(env.svc.taskCount()).toBeNull();
  });
});
