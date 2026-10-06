import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from './api.config';
import { lazyMockApiInterceptor } from './mock-api.lazy';

// `isDevMode` is a non-configurable named export of @angular/core (see
// mock-api.prod-gate.spec.ts): the test mocks the module and keeps every other export.
const isDevModeMock = jest.fn<boolean, []>();
jest.mock('@angular/core', () => {
  const actual = jest.requireActual('@angular/core');
  return { ...actual, isDevMode: (): boolean => isDevModeMock() };
});

describe('lazyMockApiInterceptor', () => {
  afterEach(() => TestBed.resetTestingModule());

  function setup(useMock: boolean): { http: HttpTestingController; client: HttpClient } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([lazyMockApiInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: useMock },
      ],
    });
    return { http: TestBed.inject(HttpTestingController), client: TestBed.inject(HttpClient) };
  }

  it('lets every request through in a prod build, also with the mock switched on', () => {
    isDevModeMock.mockReturnValue(false);
    const { http, client } = setup(true);
    client.get('/api/application-types').subscribe();
    http.expectOne('/api/application-types').flush([]);
    http.verify();
  });

  it('lets every request through when the mock is off', () => {
    isDevModeMock.mockReturnValue(true);
    const { http, client } = setup(false);
    client.get('/api/application-types').subscribe();
    http.expectOne('/api/application-types').flush([]);
    http.verify();
  });

  it('lets a request outside the API through', () => {
    isDevModeMock.mockReturnValue(true);
    const { http, client } = setup(true);
    client.get('/assets/i18n.json').subscribe();
    http.expectOne('/assets/i18n.json').flush({});
    http.verify();
  });

  it('loads the mock and lets it answer an API request', async () => {
    isDevModeMock.mockReturnValue(true);
    const { http, client } = setup(true);
    const types = await firstValueFrom(client.get<unknown[]>('/api/application-types'));
    expect(Array.isArray(types) || typeof types === 'object').toBe(true);
    http.expectNone('/api/application-types');
    http.verify();
  });
});
