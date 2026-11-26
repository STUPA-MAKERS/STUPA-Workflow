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

  it('sends the writes of a team', () => {
    api.create('Ersti', null).subscribe();
    expect(http.expectOne({ method: 'POST', url: '/api/teams' }).request.body).toEqual({ name: 'Ersti', parentId: null });
    api.patch('t-1', { name: 'Neu' }).subscribe();
    expect(http.expectOne({ method: 'PATCH', url: '/api/teams/t-1' }).request.body).toEqual({ name: 'Neu' });
    api.remove('t-1').subscribe();
    http.expectOne({ method: 'DELETE', url: '/api/teams/t-1' }).flush(null);
    api.setMember('t-1', 'p-1', 'manager').subscribe();
    expect(http.expectOne({ method: 'PUT', url: '/api/teams/t-1/members/p-1' }).request.body).toEqual({ role: 'manager' });
    api.removeMember('t-1', 'p-1').subscribe();
    http.expectOne({ method: 'DELETE', url: '/api/teams/t-1/members/p-1' }).flush({});
  });

  it('reads and saves the Info of a team (spec 003077)', () => {
    api.info('t-1').subscribe();
    const read = http.expectOne({ method: 'GET', url: '/api/teams/t-1/info' });
    expect(read.request.context.get(SKIP_LOADING)).toBe(true);
    read.flush({});
    const body = { bodyMd: 'Hallo', links: [], version: 1 };
    api.saveInfo('t-1', body).subscribe();
    expect(http.expectOne({ method: 'PUT', url: '/api/teams/t-1/info' }).request.body).toEqual(body);
  });
});
