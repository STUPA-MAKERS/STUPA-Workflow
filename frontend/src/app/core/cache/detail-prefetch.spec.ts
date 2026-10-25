import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, inject, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { LoadingService } from '@core/loading/loading.service';
import { loadingInterceptor } from '@core/loading/loading.interceptor';
import { cacheInterceptor, detailContext } from './cache.interceptor';
import { prefetchDetails, provideDetailPrefetch } from './detail-prefetch';

@Component({ standalone: true, template: '' })
class ListHost {
  private readonly http = inject(HttpClient);
  readonly rows = signal<string[]>([]);
  readonly allowed = signal(true);
  constructor() {
    prefetchDetails({
      items: this.rows,
      key: (id) => id,
      reads: (id) => [this.read(id)],
      when: this.allowed,
    });
  }
  read(id: string) {
    return this.http.get(`/api/things/${id}`, { context: detailContext() });
  }
}

describe('prefetchDetails', () => {
  let mock: HttpTestingController;

  function setup() {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([loadingInterceptor, cacheInterceptor])),
        provideHttpClientTesting(),
        provideDetailPrefetch(),
      ],
    });
    mock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(ListHost);
    return { fixture, host: fixture.componentInstance, loading: TestBed.inject(LoadingService) };
  }

  const pending = () => mock.match(() => true);
  const tick = () => new Promise((resolve) => setTimeout(resolve));

  /**
   * On the click the read ahead comes first, and the read behind it adds nothing when it is the
   * same. A detail read never runs the bar, because the detail paints the kept answer meanwhile.
   */
  it('reads the shown rows ahead four at a time, quietly, and a click paints from them', async () => {
    const { fixture, host, loading } = setup();
    const inc = jest.spyOn(loading, 'inc');
    host.rows.set(['a', 'b', 'c', 'd', 'e']);
    fixture.detectChanges();
    const first = pending();
    expect(first.map((r) => r.request.url)).toEqual(['/api/things/a', '/api/things/b', '/api/things/c', '/api/things/d']);
    expect(inc).not.toHaveBeenCalled();
    first.forEach((r) => r.flush({ id: r.request.url.slice(-1) }));
    await tick();
    const rest = pending();
    expect(rest.map((r) => r.request.url)).toEqual(['/api/things/e']);
    rest[0].flush({ id: 'e' });

    const seen: unknown[] = [];
    host.read('b').subscribe((b) => seen.push(b));
    expect(seen).toEqual([{ id: 'b' }]);
    mock.expectOne('/api/things/b').flush({ id: 'b' });
    expect(seen).toEqual([{ id: 'b' }]);
    host.read('c').subscribe((b) => seen.push(b));
    mock.expectOne('/api/things/c').flush({ id: 'c', changed: true });
    expect(seen).toEqual([{ id: 'b' }, { id: 'c' }, { id: 'c', changed: true }]);
    expect(inc).not.toHaveBeenCalled();
  });

  it('joins a read ahead still in flight instead of reading twice', () => {
    const { fixture, host } = setup();
    host.rows.set(['a']);
    fixture.detectChanges();
    const seen: unknown[] = [];
    host.read('a').subscribe((b) => seen.push(b));
    mock.expectOne('/api/things/a').flush({ id: 'a' });
    expect(seen).toEqual([{ id: 'a' }]);
  });

  it('reads a row once while fresh, nothing while not allowed, and stops with the list', async () => {
    const { fixture, host } = setup();
    host.allowed.set(false);
    host.rows.set(['a']);
    fixture.detectChanges();
    expect(pending()).toHaveLength(0);
    host.allowed.set(true);
    fixture.detectChanges();
    mock.expectOne('/api/things/a').flush(null, { status: 500, statusText: 'x' });
    await tick();
    host.rows.set(['a', 'b']);
    fixture.detectChanges();
    const b = mock.expectOne('/api/things/b');
    fixture.destroy();
    expect(b.cancelled).toBe(true);
  });
});
