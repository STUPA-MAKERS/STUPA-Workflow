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

// `isDevMode` is a non-configurable named export of @angular/core, so
// `jest.spyOn` cannot replace it. The test mocks the module and keeps every
// other export. Only `isDevMode` changes per test.
const isDevModeMock = jest.fn<boolean, []>();
jest.mock('@angular/core', () => {
  const actual = jest.requireActual('@angular/core');
  return { ...actual, isDevMode: (): boolean => isDevModeMock() };
});

/**
 * Security: the mock interceptor must never take effect in a prod build.
 *
 * This holds even when the attacker-controlled opt-ins (?mock=1, localStorage,
 * __USE_MOCK_API__) are set. The interceptor checks `isDevMode()` first. These
 * tests force `isDevMode()` to false for prod and check the pass-through with
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

    // Prod build: the mock stays off. The request reaches the real backend
    // instead of invented mock data.
    http.expectOne('/api/application-types').flush({ items: [], total: 0, limit: 20, offset: 0 });
    http.verify();
  });

  it('still short-circuits in dev mode when the mock is enabled', () => {
    isDevModeMock.mockReturnValue(true);
    const { http, client } = setup(true);

    client.get('/api/application-types').subscribe();

    // Dev or demo build: the mock still takes effect and answers with no backend.
    http.expectNone('/api/application-types');
    http.verify();
  });
});
