import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ToastService } from '@stupa-makers/ui-kit';
import { reachabilityInterceptor } from './reachability.interceptor';
import { HEALTH_POLL_MS, ServerReachabilityService, isUnreachableStatus } from './server-reachability.service';

function setup(): { http: HttpClient; ctrl: HttpTestingController; reach: ServerReachabilityService; toast: ToastService } {
  TestBed.configureTestingModule({
    providers: [provideHttpClient(withInterceptors([reachabilityInterceptor])), provideHttpClientTesting()],
  });
  return {
    http: TestBed.inject(HttpClient),
    ctrl: TestBed.inject(HttpTestingController),
    reach: TestBed.inject(ServerReachabilityService),
    toast: TestBed.inject(ToastService),
  };
}

const bar = (toast: ToastService): string | undefined =>
  toast.toasts().find((t) => t.phonePlacement === 'top' && t.variant === 'danger')?.message;

describe('ServerReachabilityService', () => {
  afterEach(() => jest.useRealTimers());

  it('counts no answer, 502, 503 and 504 as unreachable, nothing else', () => {
    expect([0, 502, 503, 504].every(isUnreachableStatus)).toBe(true);
    expect([200, 401, 403, 404, 500].some(isUnreachableStatus)).toBe(false);
  });

  /** § 000578: a 502 shows the bar after a failed health check, a 200 of the check removes it. */
  it('shows "Server nicht erreichbar" after a 502 and a failed check, and removes it after a 200', () => {
    jest.useFakeTimers();
    const { http, ctrl, reach, toast } = setup();
    http.get('/api/applications').subscribe({ error: () => undefined });
    ctrl.expectOne('/api/applications').flush('', { status: 502, statusText: 'Bad Gateway' });
    expect(reach.state()).toBe('checking');
    expect(reach.waiting()).toBe(true);

    ctrl.expectOne('/api/health').flush('', { status: 503, statusText: 'Unavailable' });
    TestBed.tick();
    expect(reach.state()).toBe('down');
    expect(bar(toast)).toBe('Server nicht erreichbar');

    jest.advanceTimersByTime(HEALTH_POLL_MS);
    ctrl.expectOne('/api/health').flush({ status: 'ok' });
    TestBed.tick();
    expect(reach.state()).toBe('up');
    expect(reach.waiting()).toBe(false);
    expect(bar(toast)).toBeUndefined();
    ctrl.verify();
  });

  /** § 000578: one route that answers 503 for its own reason shows no bar. */
  it('shows no bar when the health check answers', () => {
    const { http, ctrl, reach, toast } = setup();
    http.get('/api/admin/backups').subscribe({ error: () => undefined });
    ctrl.expectOne('/api/admin/backups').flush('', { status: 503, statusText: 'Unavailable' });
    ctrl.expectOne('/api/health').flush({ status: 'ok' });
    TestBed.tick();
    expect(reach.state()).toBe('up');
    expect(bar(toast)).toBeUndefined();
  });

  it('counts a 500 and any other API answer as reachable, and ignores other hosts', () => {
    const { http, ctrl, reach } = setup();
    http.get('https://example.org/x').subscribe({ error: () => undefined });
    ctrl.expectOne('https://example.org/x').flush('', { status: 502, statusText: 'Bad Gateway' });
    expect(reach.state()).toBe('up');
    http.get('/api/x').subscribe({ error: () => undefined });
    ctrl.expectOne('/api/x').flush('', { status: 500, statusText: 'Error' });
    expect(reach.state()).toBe('up');
    ctrl.verify();
  });

  it('ends the unreachable state on any API answer, and checks only once at a time', () => {
    const { http, ctrl, reach } = setup();
    http.get('/api/a').subscribe({ error: () => undefined });
    http.get('/api/b').subscribe({ error: () => undefined });
    ctrl.expectOne('/api/a').flush('', { status: 504, statusText: 'Timeout' });
    ctrl.expectOne('/api/b').flush('', { status: 504, statusText: 'Timeout' });
    const check = ctrl.expectOne('/api/health');
    http.get('/api/c').subscribe();
    ctrl.expectOne('/api/c').flush({});
    expect(reach.state()).toBe('up');
    check.flush({ status: 'ok' });
    ctrl.verify();
  });
});
