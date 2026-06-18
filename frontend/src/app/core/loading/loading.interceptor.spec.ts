import { TestBed } from '@angular/core/testing';
import { HttpClient, HttpContext, provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { SKIP_LOADING, loadingInterceptor, skipLoading } from './loading.interceptor';
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

  it('increments on GET start and decrements when the response succeeds', () => {
    http.get('/api/things').subscribe();
    expect(inc).toHaveBeenCalledTimes(1);
    expect(dec).not.toHaveBeenCalled();

    httpMock.expectOne('/api/things').flush([{ id: 1 }]);
    expect(dec).toHaveBeenCalledTimes(1);
  });

  it('decrements even when the GET errors (finalize)', () => {
    http.get('/api/boom').subscribe({ error: () => undefined });
    expect(inc).toHaveBeenCalledTimes(1);

    httpMock
      .expectOne('/api/boom')
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(dec).toHaveBeenCalledTimes(1);
  });

  it.each(['POST', 'PUT', 'PATCH', 'DELETE'])(
    'never triggers the overlay for %s mutations',
    (method) => {
      const url = '/api/mutate';
      const req$ =
        method === 'DELETE'
          ? http.delete(url)
          : (http as unknown as Record<string, (u: string, b: unknown) => ReturnType<HttpClient['post']>>)[
              method.toLowerCase()
            ](url, {});
      req$.subscribe();
      expect(inc).not.toHaveBeenCalled();

      httpMock.expectOne(url).flush({});
      expect(dec).not.toHaveBeenCalled();
    },
  );

  it('skips loading for GETs carrying the SKIP_LOADING context (skipLoading())', () => {
    http.get('/api/poll', { context: skipLoading() }).subscribe();
    expect(inc).not.toHaveBeenCalled();

    const req = httpMock.expectOne('/api/poll');
    expect(req.request.context.get(SKIP_LOADING)).toBe(true);
    req.flush({});
    expect(dec).not.toHaveBeenCalled();
  });

  it('still counts GETs whose context explicitly sets SKIP_LOADING=false', () => {
    http.get('/api/load', { context: new HttpContext().set(SKIP_LOADING, false) }).subscribe();
    expect(inc).toHaveBeenCalledTimes(1);
    httpMock.expectOne('/api/load').flush({});
    expect(dec).toHaveBeenCalledTimes(1);
  });
});
