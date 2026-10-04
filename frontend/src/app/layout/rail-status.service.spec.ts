import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { Subject } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Principal } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { SKIP_LOADING } from '@core/loading/loading.interceptor';
import type { MeetingStateMsg } from '@core/ws/ws-messages';
import { WsService } from '@core/ws/ws.service';
import { createLocationMock, provideLocationMock } from '../../testing/location-mock';
import { RAIL_STATUS_DEBOUNCE_MS, RAIL_STATUS_POLL_MS, RailStatusService } from './rail-status.service';

@Component({ standalone: true, template: '' })
class StubPage {}

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: [],
  groups: [],
  gremien: [{ id: 'g1', name: 'StuPa' }],
} as Principal;

const TASKS = '/api/applications/tasks';
const TIMELINE = '/api/meetings/timeline';

const meeting = (status: string) => ({
  id: 'm1',
  title: 'Sitzung',
  status,
  gremiumId: 'g1',
  scheduledAt: null,
  votes: [],
});

function setup() {
  const states = new Subject<MeetingStateMsg>();
  TestBed.configureTestingModule({
    providers: [
      provideRouter([{ path: 'a', component: StubPage }, { path: 'b', component: StubPage }]),
      provideHttpClient(),
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
  return { http, auth, svc, router, states };
}

/** Sign in and let the first load go out. */
function signIn(env: ReturnType<typeof setup>, principal: Principal = MEMBER): void {
  env.auth.ensureLoaded().subscribe();
  env.http.expectOne('/api/auth/me').flush(principal);
  TestBed.tick();
}

/** Answer one round of the two requests. */
function answer(env: ReturnType<typeof setup>, tasks: number, status = 'planned'): void {
  env.http.expectOne((r) => r.url === TASKS).flush(Array.from({ length: tasks }, (_, i) => ({ id: `t${i}` })));
  env.http.expectOne((r) => r.url === TIMELINE).flush({ items: [meeting(status)], nextCursor: null });
}

describe('RailStatusService', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('asks nothing and shows no marks while nobody is signed in', () => {
    const env = setup();
    jest.advanceTimersByTime(RAIL_STATUS_POLL_MS * 2);
    env.http.expectNone((r) => r.url === TASKS);
    expect(env.svc.taskCount()).toBeNull();
    expect(env.svc.live()).toBe(false);
  });

  it('loads the task count and the live flag at sign-in, without the loading overlay', () => {
    const env = setup();
    signIn(env);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    const tasks = env.http.expectOne((r) => r.url === TASKS);
    const timeline = env.http.expectOne((r) => r.url === TIMELINE);
    expect(tasks.request.context.get(SKIP_LOADING)).toBe(true);
    expect(timeline.request.context.get(SKIP_LOADING)).toBe(true);
    expect(timeline.request.params.get('direction')).toBe('upcoming');
    tasks.flush([{ id: 'a' }, { id: 'b' }, { id: 'c' }]);
    timeline.flush({ items: [meeting('planned'), meeting('live')], nextCursor: null });
    expect(env.svc.taskCount()).toBe(3);
    expect(env.svc.live()).toBe(true);
  });

  it('does not ask for the live flag when the principal cannot see meetings', () => {
    const env = setup();
    signIn(env, { ...MEMBER, gremien: [] } as Principal);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectOne((r) => r.url === TASKS).flush([]);
    env.http.expectNone((r) => r.url === TIMELINE);
    expect(env.svc.taskCount()).toBe(0);
    expect(env.svc.live()).toBe(false);
  });

  it('folds a burst of navigations into one request after the debounce', async () => {
    const env = setup();
    signIn(env);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    answer(env, 1);

    const nav1 = env.router.navigateByUrl('/a');
    const nav2 = env.router.navigateByUrl('/b');
    await jest.advanceTimersByTimeAsync(10);
    await Promise.all([nav1, nav2]);
    env.http.expectNone((r) => r.url === TASKS);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    answer(env, 2);
    expect(env.svc.taskCount()).toBe(2);
  });

  it('refreshes on a meeting_state frame of an open meeting channel', () => {
    const env = setup();
    signIn(env);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    answer(env, 1, 'planned');
    expect(env.svc.live()).toBe(false);

    env.states.next({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    answer(env, 1, 'live');
    expect(env.svc.live()).toBe(true);
  });

  it('polls no faster than once a minute', () => {
    const env = setup();
    signIn(env);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    answer(env, 1);

    jest.advanceTimersByTime(RAIL_STATUS_POLL_MS - RAIL_STATUS_DEBOUNCE_MS - 1);
    env.http.expectNone((r) => r.url === TASKS);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS + 1);
    answer(env, 5);
    expect(env.svc.taskCount()).toBe(5);
  });

  it('skips the poll while the tab is hidden', () => {
    const env = setup();
    signIn(env);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    answer(env, 1);

    const visibility = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    jest.advanceTimersByTime(RAIL_STATUS_POLL_MS + RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectNone((r) => r.url === TASKS);
    visibility.mockRestore();
  });

  it('keeps the count empty when the task request fails and the live flag off when the timeline fails', () => {
    const env = setup();
    signIn(env);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    env.http.expectOne((r) => r.url === TASKS).flush(null, { status: 500, statusText: 'Error' });
    env.http.expectOne((r) => r.url === TIMELINE).flush(null, { status: 500, statusText: 'Error' });
    expect(env.svc.taskCount()).toBeNull();
    expect(env.svc.live()).toBe(false);

    // The stream survives the failure: the next refresh asks again.
    env.svc.refresh();
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    answer(env, 2);
    expect(env.svc.taskCount()).toBe(2);
  });

  it('forgets the marks at sign-out', () => {
    const env = setup();
    signIn(env);
    jest.advanceTimersByTime(RAIL_STATUS_DEBOUNCE_MS);
    answer(env, 3, 'live');
    expect(env.svc.taskCount()).toBe(3);

    env.auth.handleUnauthorized();
    TestBed.tick();
    expect(env.svc.taskCount()).toBeNull();
    expect(env.svc.live()).toBe(false);
  });
});
