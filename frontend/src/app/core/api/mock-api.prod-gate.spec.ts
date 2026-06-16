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

// `isDevMode` ist ein nicht-konfigurierbarer Named-Export von @angular/core und
// lässt sich nicht per `jest.spyOn` ersetzen. Wir mocken das Modul daher und
// behalten alle übrigen Exporte bei; nur `isDevMode` ist pro Test steuerbar.
const isDevModeMock = jest.fn<boolean, []>();
jest.mock('@angular/core', () => {
  const actual = jest.requireActual('@angular/core');
  return { ...actual, isDevMode: (): boolean => isDevModeMock() };
});

/**
 * SICHERHEIT (#67): Der Mock-Interceptor darf in Prod-Builds **nie** greifen,
 * auch wenn die zur Laufzeit angreifbaren Opt-ins (?mock=1, localStorage,
 * __USE_MOCK_API__) gesetzt sind. Der Interceptor prüft `isDevMode()` zuerst;
 * hier zwingen wir `isDevMode()` auf false (Prod) und verifizieren den
 * Pass-Through, selbst bei `USE_MOCK_API === true`.
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

    // Prod-Build: Mock ist deaktiviert → die Anfrage erreicht das echte Backend,
    // statt durch erfundene Mock-Daten kurzgeschlossen zu werden.
    http.expectOne('/api/application-types').flush({ items: [], total: 0, limit: 20, offset: 0 });
    http.verify();
  });

  it('still short-circuits in dev mode when the mock is enabled', () => {
    isDevModeMock.mockReturnValue(true);
    const { http, client } = setup(true);

    client.get('/api/application-types').subscribe();

    // Dev-/Demo-Build: der Mock greift weiterhin und beantwortet ohne Backend.
    http.expectNone('/api/application-types');
    http.verify();
  });
});
