import { TestBed, fakeAsync, tick } from '@angular/core/testing';
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

  it('does nothing when the service worker is not enabled', () => {
    configure(false);
    const subscribeSpy = jest.spyOn(sw.versionUpdates, 'subscribe');
    svc.init();
    expect(subscribeSpy).not.toHaveBeenCalled();
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

  it('actively checks for updates on focus event', fakeAsync(() => {
    configure(true);
    svc.init();

    // Verify that checkForUpdate is not called initially
    expect(sw.checkForUpdate).not.toHaveBeenCalled();
    
    // Dispatch focus event
    window.dispatchEvent(new Event('focus'));
    tick();
    
    // Now checkForUpdate should have been called
    expect(sw.checkForUpdate).toHaveBeenCalled();
  }));

  it('actively checks for updates on interval', fakeAsync(() => {
    configure(true);
    svc.init();

    // Initially, no check
    expect(sw.checkForUpdate).not.toHaveBeenCalled();
    
    // Advance timers by 5 minutes (300,000 ms)
    tick(5 * 60 * 1000);
    
    // Now checkForUpdate should have been called
    expect(sw.checkForUpdate).toHaveBeenCalled();
  }));
});
