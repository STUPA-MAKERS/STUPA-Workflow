import { TestBed } from '@angular/core/testing';
import {
  HttpClient,
  HttpHeaders,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { SKIP_LOADING_HEADER, loadingInterceptor } from './loading.interceptor';
import { LoadingService } from './loading.service';

describe('loadingInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let loading: LoadingService;
  let inc: jest.SpyInstance;
  let dec: jest.SpyInstance;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([loadingInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    loading = TestBed.inject(LoadingService);
    inc = jest.spyOn(loading, 'inc');
    dec = jest.spyOn(loading, 'dec');
  });

  afterEach(() => httpMock.verify());

  it('increments on request start and decrements when the response succeeds', () => {
    http.get('/api/things').subscribe();
    expect(inc).toHaveBeenCalledTimes(1);
    expect(dec).not.toHaveBeenCalled();

    httpMock.expectOne('/api/things').flush([{ id: 1 }]);
    expect(dec).toHaveBeenCalledTimes(1);
  });

  it('decrements even when the request errors (finalize)', () => {
    http.get('/api/boom').subscribe({ error: () => undefined });
    expect(inc).toHaveBeenCalledTimes(1);

    httpMock
      .expectOne('/api/boom')
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(dec).toHaveBeenCalledTimes(1);
  });

  it('skips loading and strips the opt-out header when present', () => {
    http
      .get('/api/poll', { headers: new HttpHeaders().set(SKIP_LOADING_HEADER, '1') })
      .subscribe();

    // Neither counter touched for skip-loading requests.
    expect(inc).not.toHaveBeenCalled();

    const req = httpMock.expectOne('/api/poll');
    // The opt-out header must be removed before the request leaves the chain.
    expect(req.request.headers.has(SKIP_LOADING_HEADER)).toBe(false);
    req.flush({});
    expect(dec).not.toHaveBeenCalled();
  });
});
