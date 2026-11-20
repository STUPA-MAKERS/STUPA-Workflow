import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { NavigationEnd, Router } from '@angular/router';
import { SwUpdate } from '@angular/service-worker';
import { PAGE_RELOAD } from '@stupa-makers/ui-kit/pwa';
import { Subject, throwError } from 'rxjs';
import { appVersionInterceptor } from './app-version.interceptor';
import { APP_BUILD, AppVersionService, RELOAD_GUARD_MS, RELOAD_KEY } from './app-version.service';

interface Setup {
  http: HttpClient;
  ctrl: HttpTestingController;
  reload: jest.Mock;
  sw: {
    isEnabled: boolean;
    checkForUpdate: jest.Mock;
    activateUpdate: jest.Mock;
    unrecoverable: Subject<unknown>;
  };
  events: Subject<unknown>;
}

function setup(build = 'aaa', swEnabled = true): Setup {
  const reload = jest.fn();
  const sw = {
    isEnabled: swEnabled,
    checkForUpdate: jest.fn().mockResolvedValue(true),
    activateUpdate: jest.fn().mockResolvedValue(true),
    unrecoverable: new Subject<unknown>(),
  };
  const events = new Subject<unknown>();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([appVersionInterceptor])),
      provideHttpClientTesting(),
      { provide: APP_BUILD, useValue: build },
      { provide: PAGE_RELOAD, useValue: reload },
      { provide: SwUpdate, useValue: sw },
      { provide: Router, useValue: { events } },
    ],
  });
  TestBed.inject(AppVersionService).init();
  return {
    http: TestBed.inject(HttpClient),
    ctrl: TestBed.inject(HttpTestingController),
    reload,
    sw,
    events,
  };
}

function answer(s: Setup, version: string | null, status = 200): void {
  s.http.get('/api/applications').subscribe({ error: () => undefined });
  const headers: Record<string, string> = version === null ? {} : { 'X-App-Version': version };
  s.ctrl.expectOne('/api/applications').flush(status === 200 ? [] : '', {
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    headers,
  });
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

describe('AppVersionService', () => {
  afterEach(() => {
    sessionStorage.clear();
    document.body.innerHTML = '';
  });

  /** § 002151: another server version activates the update and reloads at once. */
  it('reloads through the service worker when the header names another build', async () => {
    const s = setup();
    answer(s, 'bbb');
    await flush();
    expect(s.sw.checkForUpdate).toHaveBeenCalled();
    expect(s.sw.activateUpdate).toHaveBeenCalled();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  /** § 002151: an error answer carries the header too. */
  it('reloads on the header of an error answer', async () => {
    const s = setup('aaa', false);
    answer(s, 'bbb', 404);
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  it('does nothing for the same build, a missing header or the dev build', async () => {
    const s = setup();
    answer(s, 'aaa');
    answer(s, null);
    await flush();
    expect(s.reload).not.toHaveBeenCalled();
    TestBed.resetTestingModule();
    const d = setup('dev');
    answer(d, 'bbb');
    await flush();
    expect(d.reload).not.toHaveBeenCalled();
  });

  /** § 002151: a focused text field holds the reload until the next page change. */
  it('waits while a text field has the focus and reloads at the next page change', async () => {
    const s = setup();
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    answer(s, 'bbb');
    await flush();
    expect(s.reload).not.toHaveBeenCalled();
    s.events.next(new NavigationEnd(1, '/a', '/a'));
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  /** § 002151: the next answer while no text field has the focus reloads. */
  it('reloads at the next answer after the focus left the field', async () => {
    const s = setup();
    const area = document.createElement('textarea');
    document.body.appendChild(area);
    area.focus();
    answer(s, 'bbb');
    await flush();
    expect(s.reload).not.toHaveBeenCalled();
    area.blur();
    answer(s, 'bbb');
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  /** § 002152: the same server version reloads only once within the guard time. */
  it('does not reload a second time for the same server version', async () => {
    sessionStorage.setItem(RELOAD_KEY, JSON.stringify({ version: 'bbb', at: Date.now() }));
    const s = setup();
    answer(s, 'bbb');
    await flush();
    expect(s.reload).not.toHaveBeenCalled();
    answer(s, 'ccc');
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
    expect(JSON.parse(sessionStorage.getItem(RELOAD_KEY) ?? '{}').version).toBe('ccc');
  });

  it('reloads again for the same version after the guard time', async () => {
    sessionStorage.setItem(
      RELOAD_KEY,
      JSON.stringify({ version: 'bbb', at: Date.now() - RELOAD_GUARD_MS - 1 }),
    );
    const s = setup();
    answer(s, 'bbb');
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  it('reloads at once when the service worker cache is broken', () => {
    const s = setup();
    s.sw.unrecoverable.next({});
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  it('reloads even when the service worker update fails', async () => {
    const s = setup();
    s.sw.checkForUpdate.mockRejectedValue(new Error('offline'));
    answer(s, 'bbb');
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  it('runs the build dev by default', () => {
    TestBed.configureTestingModule({});
    expect(TestBed.inject(APP_BUILD)).toBe('dev');
  });

  it('does not read the header of a request to another host', async () => {
    const s = setup();
    s.http.get('https://example.org/x').subscribe();
    s.ctrl.expectOne('https://example.org/x').flush({}, { headers: { 'X-App-Version': 'bbb' } });
    await flush();
    expect(s.reload).not.toHaveBeenCalled();
  });

  it('ignores an error that is not an HTTP answer', async () => {
    const s = setup();
    s.http.get('/api/applications').subscribe({ error: () => undefined });
    s.ctrl.expectOne('/api/applications').error(new ProgressEvent('error'));
    await flush();
    expect(s.reload).not.toHaveBeenCalled();
  });

  it('does not wait for a checkbox, but waits for an editable element', async () => {
    const s = setup();
    const box = document.createElement('input');
    box.type = 'checkbox';
    document.body.appendChild(box);
    box.focus();
    answer(s, 'bbb');
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);

    TestBed.resetTestingModule();
    sessionStorage.clear();
    const t = setup();
    const div = document.createElement('div');
    div.contentEditable = 'true';
    Object.defineProperty(div, 'isContentEditable', { value: true });
    div.tabIndex = 0;
    document.body.appendChild(div);
    div.focus();
    answer(t, 'bbb');
    await flush();
    expect(t.reload).not.toHaveBeenCalled();
  });

  it('reloads when the storage holds no valid entry or throws', async () => {
    sessionStorage.setItem(RELOAD_KEY, '{broken');
    const s = setup();
    const spy = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    answer(s, 'bbb');
    await flush();
    spy.mockRestore();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  it('starts once, ignores a page change without a waiting reload and reloads only once', async () => {
    const s = setup();
    TestBed.inject(AppVersionService).init();
    s.events.next(new NavigationEnd(1, '/a', '/a'));
    await flush();
    expect(s.reload).not.toHaveBeenCalled();
    answer(s, 'bbb');
    answer(s, 'ccc');
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  it('does not wait when no element has the focus', async () => {
    const s = setup();
    const spy = jest.spyOn(document, 'activeElement', 'get').mockReturnValue(null);
    answer(s, 'bbb');
    spy.mockRestore();
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
  });

  it('passes an error that is not an HTTP answer through', async () => {
    const reload = jest.fn();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(
          withInterceptors([appVersionInterceptor, () => throwError(() => new Error('boom'))]),
        ),
        { provide: PAGE_RELOAD, useValue: reload },
        { provide: SwUpdate, useValue: { isEnabled: false } },
        { provide: Router, useValue: { events: new Subject<unknown>() } },
      ],
    });
    const err = jest.fn();
    TestBed.inject(HttpClient).get('/api/x').subscribe({ error: err });
    await flush();
    expect(err).toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
  });
});
