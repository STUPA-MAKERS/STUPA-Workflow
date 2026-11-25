import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { SKIP_LOADING } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from './api.config';
import { TeamsApiService } from './teams.service';

describe('TeamsApiService', () => {
  let api: TeamsApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    api = TestBed.inject(TeamsApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('lists the teams without the global overlay', () => {
    let rows: unknown;
    api.list().subscribe((r) => (rows = r));
    const req = http.expectOne('/api/teams');
    expect(req.request.context.get(SKIP_LOADING)).toBe(true);
    req.flush([]);
    expect(rows).toEqual([]);
  });

  it('reads one team', () => {
    api.detail('t-1').subscribe();
    const req = http.expectOne('/api/teams/t-1');
    expect(req.request.method).toBe('GET');
    req.flush({ team: {}, members: [], subTeams: [] });
  });
});
