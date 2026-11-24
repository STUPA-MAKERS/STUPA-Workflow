import { DOCUMENT } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { DestroyRef, Injectable, InjectionToken, Injector, inject } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { SwUpdate } from '@angular/service-worker';
import { skipLoading } from '@stupa-makers/ui-kit';
import { PAGE_RELOAD } from '@stupa-makers/ui-kit/pwa';
import { Subscription, filter, firstValueFrom, from, map, race, timer } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import { PageResumeService } from '@core/browser/page-resume.service';
import { APP_BUILD_ID } from './build-id';

/** The response header with the build ID of the frontend that the server serves (§ 002150). */
export const APP_VERSION_HEADER = 'X-App-Version';

/** The build ID of the running frontend. A token, so that a test can set it. */
export const APP_BUILD = new InjectionToken<string>('APP_BUILD', {
  providedIn: 'root',
  factory: () => APP_BUILD_ID,
});

/** The build ID that never reloads: a local build or `ng serve`. */
export const DEV_BUILD = 'dev';

/** The session storage key of the last reload, for the loop guard (§ui-kit:002152). */
export const RELOAD_KEY = 'appVersionReload';

/** How long the app does not reload a third time for the same server version (§ui-kit:002152). */
export const RELOAD_GUARD_MS = 10 * 60 * 1000;

/** The longest wait for the removal of the service worker before the second reload. */
export const SW_REMOVE_MS = 5_000;

/**
 * Removes every service worker registration of the page (§002340). A reload after the
 * removal loads the app from the network. A token, so that a test can replace it.
 */
export const SW_UNREGISTER = new InjectionToken<() => Promise<unknown>>('SW_UNREGISTER', {
  providedIn: 'root',
  factory: () => {
    const sw = inject(DOCUMENT).defaultView?.navigator.serviceWorker;
    return async () => {
      if (!sw) return;
      const registrations = await sw.getRegistrations();
      await Promise.all(registrations.map((r) => r.unregister()));
    };
  },
});

/** The input types that take no typed text, so their focus does not hold the reload. */
const NO_TEXT_INPUTS = new Set([
  'button',
  'checkbox',
  'color',
  'file',
  'hidden',
  'image',
  'radio',
  'range',
  'reset',
  'submit',
]);

/**
 * The reload of the app when the server serves another frontend build (§ui-kit:002151).
 *
 * `appVersionInterceptor` reports the header `X-App-Version` of each API answer. When the
 * value is not the build ID of the running app, the service reloads the page at once. The
 * app shows no update notice.
 *
 * The reload waits for no download of the service worker (§002340). The service worker
 * loads a page from the network first (`navigationRequestStrategy: "freshness"` in
 * `ngsw-config.json`), and the new `index.html` names the new files, which the network
 * serves while the service worker does not hold them. When the next answer after that
 * reload still reports the same server version, the service removes the service worker and
 * reloads a second time, so that a service worker of an older config cannot hold the old
 * version.
 *
 * When the page comes back to the user (§002341), the service reads `/api/health` once, so
 * that a page that only talks over a WebSocket notices a new version too.
 *
 * While a text field has the focus, the reload waits (§ui-kit:002151): it runs at the next
 * page change or at the next reported answer while no text field has the focus, so typed
 * text is not lost.
 *
 * The loop guard (§ui-kit:002152): before a reload, the service writes the server version,
 * the number of reloads for it and the time into the session storage. After two reloads
 * for the same version within {@link RELOAD_GUARD_MS}, the service does not reload again.
 * A missing header or the build ID `dev` never reloads.
 *
 * When the cache of the running version is broken (`unrecoverable`), the service reloads at
 * once, because the page cannot load its lazy chunks.
 */
@Injectable({ providedIn: 'root' })
export class AppVersionService {
  private readonly updates = inject(SwUpdate);
  private readonly reloadPage = inject(PAGE_RELOAD);
  private readonly doc = inject(DOCUMENT);
  private readonly router = inject(Router);
  private readonly build = inject(APP_BUILD);
  private readonly unregister = inject(SW_UNREGISTER);
  private readonly injector = inject(Injector);
  private readonly subscriptions = new Subscription();
  private started = false;
  private reloading = false;
  /** The server version of a reload that waits for the end of typing. */
  private pending: string | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.subscriptions.unsubscribe());
  }

  /** Starts the watch of the router, of the page returns and of the service worker. */
  init(): void {
    if (this.started) return;
    this.started = true;
    if (this.updates.isEnabled) {
      this.subscriptions.add(this.updates.unrecoverable.subscribe(() => this.reloadPage()));
    }
    this.subscriptions.add(
      this.router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => {
        if (this.pending !== null) void this.reload(this.pending);
      }),
    );
    if (this.build !== DEV_BUILD) {
      this.subscriptions.add(
        this.injector.get(PageResumeService).resume$.subscribe(() => this.probe()),
      );
    }
  }

  /** Takes the version header of one API answer. */
  report(serverVersion: string | null): void {
    if (!serverVersion || this.build === DEV_BUILD || serverVersion === this.build) return;
    if (this.tries(serverVersion) >= 2) return;
    if (this.typing()) {
      this.pending = serverVersion;
      return;
    }
    void this.reload(serverVersion);
  }

  /** One read of the API after a return of the page; the interceptor reports its header. */
  private probe(): void {
    const http = this.injector.get(HttpClient);
    const base = this.injector.get(API_BASE_URL);
    http
      .get(`${base}/health`, { context: skipLoading() })
      .subscribe({ error: () => undefined });
  }

  private async reload(serverVersion: string): Promise<void> {
    if (this.reloading) return;
    const tries = this.tries(serverVersion);
    if (tries >= 2) return;
    this.reloading = true;
    this.pending = null;
    this.remember(serverVersion, tries + 1);
    if (tries === 1) await settle(this.unregister(), SW_REMOVE_MS);
    this.reloadPage();
  }

  /** True while the focus is in a field that takes typed text. */
  private typing(): boolean {
    const el = this.doc.activeElement;
    if (!(el instanceof HTMLElement)) return false;
    if (
      el.isContentEditable ||
      el instanceof HTMLTextAreaElement ||
      el instanceof HTMLSelectElement
    ) {
      return true;
    }
    return el instanceof HTMLInputElement && !NO_TEXT_INPUTS.has(el.type);
  }

  /** The reloads for this server version within the guard time. */
  private tries(serverVersion: string): number {
    try {
      const raw = this.doc.defaultView?.sessionStorage.getItem(RELOAD_KEY);
      if (!raw) return 0;
      const last = JSON.parse(raw) as { version?: unknown; at?: unknown; tries?: unknown };
      if (
        last.version !== serverVersion ||
        typeof last.at !== 'number' ||
        Date.now() - last.at >= RELOAD_GUARD_MS
      ) {
        return 0;
      }
      return typeof last.tries === 'number' ? last.tries : 2;
    } catch {
      return 0;
    }
  }

  private remember(serverVersion: string, tries: number): void {
    try {
      this.doc.defaultView?.sessionStorage.setItem(
        RELOAD_KEY,
        JSON.stringify({ version: serverVersion, at: Date.now(), tries }),
      );
    } catch {
      /* Without storage the guard is off; the reload still runs. */
    }
  }
}

/**
 * The value of `work`, or `undefined` when it fails or does not end within `ms`. The timer
 * ends with it.
 */
function settle<T>(work: Promise<T>, ms: number): Promise<T | undefined> {
  return firstValueFrom(race(from(work), timer(ms).pipe(map(() => undefined)))).catch(
    () => undefined,
  );
}
