import { TestBed } from '@angular/core/testing';
import { SwUpdate, type VersionEvent } from '@angular/service-worker';
import { Subject } from 'rxjs';
import { SwUpdateService } from './sw-update.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';

/** Controllable SwUpdate stub: tests push version events and assert activation. */
class FakeSwUpdate {
  isEnabled = true;
  readonly versionUpdates = new Subject<VersionEvent>();
  activateUpdate = jest.fn(() => Promise.resolve(true));
  checkForUpdate = jest.fn(async () => false);
}

describe('SwUpdateService', () => {
  let svc: SwUpdateService;
  let sw: FakeSwUpdate;
  let toast: ToastService;
  let showSpy: jest.SpyInstance;

  function configure(enabled: boolean): void {
    sw = new FakeSwUpdate();
    sw.isEnabled = enabled;
    TestBed.configureTestingModule({
      providers: [{ provide: SwUpdate, useValue: sw }],
    });
    svc = TestBed.inject(SwUpdateService);
    toast = TestBed.inject(ToastService);
    showSpy = jest.spyOn(toast, 'show');
  }

  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('does nothing when the service worker is not enabled', () => {
    configure(false);
    const subscribeSpy = jest.spyOn(sw.versionUpdates, 'subscribe');
    svc.init();
    expect(subscribeSpy).not.toHaveBeenCalled();
    expect(sw.checkForUpdate).not.toHaveBeenCalled();
    sw.versionUpdates.next({ type: 'VERSION_READY' } as VersionEvent);
    expect(sw.activateUpdate).not.toHaveBeenCalled();
    expect(showSpy).not.toHaveBeenCalled();
  });

  it('activates the update and shows a persistent toast on VERSION_READY', async () => {
    configure(true);
    const i18n = TestBed.inject(I18nService);
    const translated = i18n.translate('pwa.updateReady');
    svc.init();

    sw.versionUpdates.next({
      type: 'VERSION_READY',
      currentVersion: { hash: 'a' },
      latestVersion: { hash: 'b' },
    } as VersionEvent);

    expect(sw.activateUpdate).toHaveBeenCalledTimes(1);
    // Toast fires after the activation promise resolves.
    await Promise.resolve();
    await Promise.resolve();
    expect(showSpy).toHaveBeenCalledWith(translated, 'info', 0);
  });

  it('ignores version events other than VERSION_READY', () => {
    configure(true);
    svc.init();
    sw.versionUpdates.next({ type: 'VERSION_DETECTED' } as VersionEvent);
    sw.versionUpdates.next({
      type: 'NO_NEW_VERSION_DETECTED',
    } as VersionEvent);
    expect(sw.activateUpdate).not.toHaveBeenCalled();
    expect(showSpy).not.toHaveBeenCalled();
  });

  it('checks for updates after a delay to allow SW registration (bootstrap fix)', () => {
    configure(true);
    svc.init();

    // Initially, checkForUpdate should not be called (timeout not yet fired)
    expect(sw.checkForUpdate).not.toHaveBeenCalled();

    // Advance time by 1 second (the setTimeout delay)
    jest.advanceTimersByTime(1000);

    // Now checkForUpdate should have been called (after SW registration time)
    expect(sw.checkForUpdate).toHaveBeenCalled();
  });

  it('sets up periodic polling after initial check', () => {
    configure(true);
    svc.init();

    // Advance time to trigger the initial check
    jest.advanceTimersByTime(1000);
    expect(sw.checkForUpdate).toHaveBeenCalledTimes(1);

    // Reset the mock to track future calls
    sw.checkForUpdate.mockClear();

    // Advance by 5 minutes to trigger the periodic polling
    jest.advanceTimersByTime(5 * 60 * 1000);

    // Now the periodic interval should have triggered checkForUpdate
    expect(sw.checkForUpdate).toHaveBeenCalled();
  });
});
