import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { SKIP_LOADING } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { PaperlessService, openInPaperless, paperlessLink } from './paperless.service';

@Component({ standalone: true, template: '' })
class HostComponent {
  readonly id = signal<string | null>(null);
  readonly link = paperlessLink('protocol', this.id);
}

/** § F/integrations/paperless/002525: the entry `In Paperless öffnen`. */
describe('PaperlessService', () => {
  let http: HttpTestingController;
  let allowed: boolean;

  beforeEach(() => {
    allowed = true;
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { can: (p: string) => allowed && p === 'paperless.use' } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('reads the address of the filed document without the loading bar', () => {
    let url: string | null | undefined;
    TestBed.inject(PaperlessService)
      .documentUrl('application', 'a1')
      .subscribe((v) => (url = v));
    const req = http.expectOne({ method: 'GET', url: '/api/paperless/documents/application/a1' });
    expect(req.request.context.get(SKIP_LOADING)).toBe(true);
    req.flush({ url: 'https://paperless.example.org/documents/7/details', documentId: 7 });
    expect(url).toBe('https://paperless.example.org/documents/7/details');
  });

  it('asks nothing without the right', () => {
    allowed = false;
    let url: string | null | undefined;
    TestBed.inject(PaperlessService)
      .documentUrl('plan', 'p1')
      .subscribe((v) => (url = v));
    expect(url).toBeNull();
  });

  it('has no address after an error', () => {
    let url: string | null | undefined;
    TestBed.inject(PaperlessService)
      .documentUrl('plan', 'p1')
      .subscribe((v) => (url = v));
    http.expectOne('/api/paperless/documents/plan/p1').flush(null, { status: 502, statusText: 'Bad Gateway' });
    expect(url).toBeNull();
  });

  it('follows the id of the element as a signal', () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance.link()).toBeNull();
    fixture.componentInstance.id.set('m1');
    fixture.detectChanges();
    http.expectOne('/api/paperless/documents/protocol/m1').flush({ url: 'https://p.example.org/documents/1/details', documentId: 1 });
    expect(fixture.componentInstance.link()).toBe('https://p.example.org/documents/1/details');
    fixture.componentInstance.id.set(null);
    fixture.detectChanges();
    expect(fixture.componentInstance.link()).toBeNull();
  });

  it('opens the document in a new tab without an opener', () => {
    const open = jest.spyOn(window, 'open').mockReturnValue(null);
    openInPaperless('https://p.example.org/documents/1/details');
    expect(open).toHaveBeenCalledWith('https://p.example.org/documents/1/details', '_blank', 'noopener');
    open.mockRestore();
  });

  /** § F/integrations/paperless/002512, 002527: the state of the insert, read once. */
  it('reads once whether the insert is on, and not at all without the right', () => {
    const api = TestBed.inject(PaperlessService);
    const seen: boolean[] = [];
    api.insertOn().subscribe((v) => seen.push(v));
    api.insertOn().subscribe((v) => seen.push(v));
    http.expectOne('/api/paperless/insert').flush({ enabled: true });
    expect(seen).toEqual([true, true]);

    allowed = false;
    api.insertOn().subscribe((v) => seen.push(v));
    expect(seen).toEqual([true, true, false]);
  });

  it('counts the insert as off after an error', () => {
    let on: boolean | undefined;
    TestBed.inject(PaperlessService)
      .insertOn()
      .subscribe((v) => (on = v));
    http.expectOne('/api/paperless/insert').flush(null, { status: 500, statusText: 'x' });
    expect(on).toBe(false);
  });

  /** § 002534, 002528: the search and the copy. */
  it('searches Paperless and copies a document into the protocol of a Sitzung', () => {
    const api = TestBed.inject(PaperlessService);
    api.search('beamer').subscribe();
    const search = http.expectOne((r) => r.url === '/api/paperless/search');
    expect(search.request.params.get('q')).toBe('beamer');
    search.flush([]);

    let name: string | undefined;
    api.insert('m1', 418).subscribe((copy) => (name = copy.name));
    const insert = http.expectOne({ method: 'POST', url: '/api/meetings/m1/documents/paperless' });
    expect(insert.request.body).toEqual({ documentId: 418 });
    insert.flush({ name: 'Angebot.pdf', url: '/api/media/documents/d1' });
    expect(name).toBe('Angebot.pdf');
  });
});
