import { TestBed } from '@angular/core/testing';
import {
  HttpClient,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { USE_MOCK_API } from './api.config';
import { mockApiInterceptor } from './mock-api.interceptor';

// `isDevMode` is a non-configurable named export of @angular/core and cannot be
// replaced via `jest.spyOn`. We therefore mock the module and keep all other
// exports; only `isDevMode` is controllable per test.
const isDevModeMock = jest.fn<boolean, []>();
jest.mock('@angular/core', () => {
  const actual = jest.requireActual('@angular/core');
  return { ...actual, isDevMode: (): boolean => isDevModeMock() };
});

/**
 * Security: the mock interceptor must never take effect in prod builds, even
 * when the runtime-attackable opt-ins (?mock=1, localStorage, __USE_MOCK_API__)
 * are set. The interceptor checks `isDevMode()` first; here we force
 * `isDevMode()` to false (prod) and verify the pass-through, even with
 * `USE_MOCK_API === true`.
 */
describe('mockApiInterceptor — production gate', () => {
  afterEach(() => {
    jest.restoreAllMocks();
    TestBed.resetTestingModule();
  });

  function setup(useMock: boolean): { http: HttpTestingController; client: HttpClient } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([mockApiInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: useMock },
      ],
    });
    return {
      http: TestBed.inject(HttpTestingController),
      client: TestBed.inject(HttpClient),
    };
  }

  it('passes /api/ requests through to the real backend when not in dev mode (mock enabled)', () => {
    isDevModeMock.mockReturnValue(false);
    const { http, client } = setup(true);

    client.get('/api/application-types').subscribe();

    // Prod build: mock is disabled → the request reaches the real backend
    // instead of being short-circuited by invented mock data.
    http.expectOne('/api/application-types').flush({ items: [], total: 0, limit: 20, offset: 0 });
    http.verify();
  });

  it('still short-circuits in dev mode when the mock is enabled', () => {
    isDevModeMock.mockReturnValue(true);
    const { http, client } = setup(true);

    client.get('/api/application-types').subscribe();

    // Dev/demo build: the mock still takes effect and answers without a backend.
    http.expectNone('/api/application-types');
    http.verify();
  });
});
