import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { LoadingService, loadingInterceptor } from '@stupa-makers/ui-kit';
import { cacheInterceptor, detailContext } from './cache.interceptor';
import { prefetchDetails, provideDetailPrefetch } from './detail-prefetch';

@Component({
  changeDetection: ChangeDetectionStrategy.Eager,
  standalone: true,
  template: `@for (id of rows(); track id) {<a [attr.href]="'/things/' + id + '?tab=x'" [id]="'row-' + id">{{ id }}</a>}`,
})
class ListHost {
  private readonly http = inject(HttpClient);
  readonly rows = signal<string[]>([]);
  readonly allowed = signal(true);
  constructor() {
    prefetchDetails({
      items: this.rows,
      key: (id) => id,
      reads: (id) => [this.read(id), this.http.get(`/api/things/${id}/more`, { context: detailContext() })],
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

  const row = (fixture: { nativeElement: HTMLElement }, id: string) =>
    fixture.nativeElement.querySelector(`#row-${id}`) as HTMLElement;
  const press = (el: HTMLElement, type: string, pointerType = 'touch') => {
    const event = new Event(type, { bubbles: true }) as Event & { pointerType: string };
    Object.defineProperty(event, 'pointerType', { value: pointerType });
    el.dispatchEvent(event);
  };

  /**
   * Without a sign of intent only the first read of the top five rows runs, four at a time and
   * quietly; a click paints from it, and the read behind it adds nothing when it is the same.
   */
  it('reads the first read of the top five rows ahead, quietly, and a click paints from it', async () => {
    const { fixture, host, loading } = setup();
    const inc = jest.spyOn(loading, 'inc');
    host.rows.set(['a', 'b', 'c', 'd', 'e', 'f']);
    fixture.detectChanges();
    const first = pending();
    expect(first.map((r) => r.request.url)).toEqual(['/api/things/a', '/api/things/b', '/api/things/c', '/api/things/d']);
    expect(inc).not.toHaveBeenCalled();
    first.forEach((r) => r.flush({ id: r.request.url.slice(-1) }));
    await tick();
    const rest = pending();
    expect(rest.map((r) => r.request.url)).toEqual(['/api/things/e']);
    rest[0].flush({ id: 'e' });
    await tick();
    expect(pending()).toHaveLength(0);

    const seen: unknown[] = [];
    host.read('b').subscribe((b) => seen.push(b));
    expect(seen).toEqual([{ id: 'b' }]);
    mock.expectOne('/api/things/b').flush({ id: 'b' });
    expect(seen).toEqual([{ id: 'b' }]);
    expect(inc).not.toHaveBeenCalled();
  });

  it('reads all reads of a row on a press, the focus or a mouse over its link, once while fresh', async () => {
    const { fixture, host } = setup();
    host.rows.set(['a', 'b', 'c', 'd', 'e', 'f', 'g']);
    fixture.detectChanges();
    pending().forEach((r) => r.flush({}));
    await tick();
    pending().forEach((r) => r.flush({}));
    await tick();

    press(row(fixture, 'f'), 'pointerdown');
    const f = pending();
    expect(f.map((r) => r.request.url)).toEqual(['/api/things/f', '/api/things/f/more']);
    f.forEach((r) => r.flush({}));
    await tick();
    press(row(fixture, 'f'), 'pointerdown');
    expect(pending()).toHaveLength(0);

    press(row(fixture, 'a'), 'focusin');
    const a = pending();
    expect(a.map((r) => r.request.url)).toEqual(['/api/things/a/more']);
    a.forEach((r) => r.flush({}));
    await tick();

    press(row(fixture, 'g'), 'pointerover', 'touch');
    expect(pending()).toHaveLength(0);
    press(row(fixture, 'g'), 'pointerover', 'mouse');
    expect(pending().map((r) => r.request.url)).toEqual(['/api/things/g', '/api/things/g/more']);
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
    press(row(fixture, 'a'), 'pointerdown');
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
