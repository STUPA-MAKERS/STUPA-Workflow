import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ApiClient } from './api-client.service';
import { USE_MOCK_API } from './api.config';
import { mockApiInterceptor } from './mock-api.interceptor';

describe('mockApiInterceptor', () => {
  function setup(useMock: boolean): { api: ApiClient; http: HttpTestingController } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([mockApiInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: useMock },
      ],
    });
    return { api: TestBed.inject(ApiClient), http: TestBed.inject(HttpTestingController) };
  }

  it('short-circuits known GET endpoints with canned data', (done) => {
    const { api, http } = setup(true);
    api.applicationTypes().subscribe((types) => {
      expect(types.length).toBeGreaterThan(0);
      done();
    });
    http.expectNone('/api/application-types'); // handled by the mock, never hits the backend
  });

  it('passes through when the mock is disabled', () => {
    const { api, http } = setup(false);
    api.applicationTypes().subscribe();
    http.expectOne('/api/application-types').flush([]);
    http.verify();
  });
});
