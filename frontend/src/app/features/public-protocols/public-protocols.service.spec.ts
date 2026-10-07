import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { PublicProtocolsService, protocolParams } from './public-protocols.service';

describe('PublicProtocolsService', () => {
  let api: PublicProtocolsService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(PublicProtocolsService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('builds the query and leaves empty filters out', () => {
    expect(protocolParams({}).toString()).toBe('');
    expect(
      protocolParams({
        gremium: ['g-1', 'g-2'],
        semester: 'ws-2026',
        q: '  Haushalt  ',
        limit: 20,
        offset: 40,
      }).toString(),
    ).toBe('gremium=g-1&gremium=g-2&semester=ws-2026&q=Haushalt&limit=20&offset=40');
    expect(protocolParams({ q: 'x'.repeat(150) }).get('q')).toHaveLength(100);
    expect(protocolParams({ q: '   ', offset: 0 }).toString()).toBe('');
  });

  it('reads the public routes', () => {
    api.gremien().subscribe();
    http.expectOne('/api/public/gremien').flush([]);
    api.list({ limit: 3 }).subscribe();
    http.expectOne('/api/public/protocols?limit=3').flush({ items: [], total: 0, limit: 3, offset: 0 });
    api.list().subscribe();
    http.expectOne('/api/public/protocols').flush({ items: [], total: 0, limit: 20, offset: 0 });
    api.semesters({ gremium: ['g-1'], q: 'a', semester: 'ss-2026' }).subscribe();
    http.expectOne('/api/public/protocols/semesters?gremium=g-1&q=a').flush([]);
    api.semesters().subscribe();
    http.expectOne('/api/public/protocols/semesters').flush([]);
    api.detail('p 1').subscribe();
    const req = http.expectOne('/api/public/protocols/p%201');
    expect(req.request.method).toBe('GET');
    req.flush({});
    expect(api.pdfUrl('p-1')).toBe('/api/public/protocols/p-1/pdf');
  });
});
