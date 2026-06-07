import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { DelegationApiService } from './delegations-api.service';
import type { DelegationInput } from './delegations.models';

const INPUT: DelegationInput = {
  principalId: 'p-1',
  roleId: 'r-1',
  gremiumId: null,
  validFrom: null,
  validUntil: '2099-01-01T00:00',
  delegateVoting: true,
};

describe('DelegationApiService — mock mode', () => {
  function svc(): DelegationApiService {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: true },
      ],
    });
    return TestBed.inject(DelegationApiService);
  }

  it('starts empty, creates and then revokes a delegation', async () => {
    const s = svc();
    expect(await firstValueFrom(s.list())).toEqual([]);

    const created = await firstValueFrom(s.create(INPUT));
    expect(created.id).toBeTruthy();
    expect(created.delegateVoting).toBe(true);
    expect(created.active).toBe(true);

    const listed = await firstValueFrom(s.list());
    expect(listed).toHaveLength(1);

    await firstValueFrom(s.revoke(created.id));
    expect(await firstValueFrom(s.list())).toEqual([]);
  });
});

describe('DelegationApiService — real mode', () => {
  let http: HttpTestingController;
  let s: DelegationApiService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    s = TestBed.inject(DelegationApiService);
  });

  afterEach(() => http.verify());

  it('GET /api/delegations', () => {
    s.list().subscribe();
    const req = http.expectOne('/api/delegations');
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  it('POST /api/delegations with the input body', () => {
    s.create(INPUT).subscribe();
    const req = http.expectOne('/api/delegations');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(INPUT);
    req.flush({ ...INPUT, id: 'x', delegatedBy: 'me', grantedBy: 'me', active: true });
  });

  it('DELETE /api/delegations/{id}', () => {
    s.revoke('del-9').subscribe();
    const req = http.expectOne('/api/delegations/del-9');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });
});
