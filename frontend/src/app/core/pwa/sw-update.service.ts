import { Injectable, inject } from '@angular/core';
import { SwUpdate, type VersionReadyEvent } from '@angular/service-worker';
import { filter, concatMap } from 'rxjs';
import { interval, fromEvent } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';

/**
 * PWA-Update-Fluss (#5): meldet sich der Service Worker mit einer neuen
 * App-Version (`VERSION_READY`), wird sie aktiviert und ein dauerhafter Toast
 * weist auf das nötige Neuladen hin. Ohne SW (Dev-Modus, alte Browser) ist
 * `isEnabled` false und nichts passiert.
 *
 * Aktive Aktualisierungserkennung: Der Service prüft auf Updates bei:
 * - Nach einer kurzen Verzögerung beim App-Start (boostrap-Deadlock überwinden)
 * - Regelmäßigen Intervallen (alle 5 Minuten)
 * - Wenn die App in den Vordergrund rückt (focus event)
 * → Benutzer sehen das Toast "neue Version verfügbar" zeitnah nach Deployments
 *
 * BOOTSTRAP DEADLOCK FIX: Alte Versionen haben die neue Polling-Logik nicht.
 * Ohne initialen Update-Check beim Start würden sie nie die neue Version
 * laden und damit nie die Polling-Logik bekommen. Daher wird checkForUpdate()
 * nach einer kurzen Verzögerung aufgerufen, um sicherzustellen, dass der
 * Service Worker bereits registriert ist.
 */
@Injectable({ providedIn: 'root' })
export class SwUpdateService {
  private readonly updates = inject(SwUpdate);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  init(): void {
    if (!this.updates.isEnabled) return;

    // Höre auf Updates, die bereit zur Aktivierung sind
    this.updates.versionUpdates
      .pipe(filter((e): e is VersionReadyEvent => e.type === 'VERSION_READY'))
      .subscribe(() => {
        void this.updates.activateUpdate().then(() => {
          this.toast.show(this.i18n.translate('pwa.updateReady'), 'info', 0);
        });
      });

    // BOOTSTRAP-FIX: Warte eine kurze Zeit (1 Sekunde), damit der Service Worker
    // Zeit hat, sich zu registrieren, bevor wir den ersten Update-Check durchführen.
    // Die registerWhenStable-Strategie registriert den SW nach 30s oder wenn die App
    // stabil ist. Mit dieser Verzögerung geben wir dem SW Zeit, registriert zu werden,
    // bevor wir checkForUpdate() aufrufen.
    setTimeout(() => {
      this.checkForUpdatesOnce();
      this.setupPeriodicPolling();
      this.setupFocusListener();
    }, 1000);
  }

  private checkForUpdatesOnce(): void {
    // Versuche SOFORT einen Update-Check (nachdem der SW registriert ist).
    // Dies überwindet das Deadlock-Problem, bei dem alte Versionen ohne Polling
    // nie die neue Version mit Polling-Logik laden würden.
    void this.updates.checkForUpdate().catch(() => {
      // Fehler ignorieren und weitermachen
    });
  }

  private setupPeriodicPolling(): void {
    // Prüfe alle 5 Minuten auf Updates (300.000 ms)
    interval(5 * 60 * 1000)
      .pipe(concatMap(() => this.updates.checkForUpdate()))
      .subscribe();
  }

  private setupFocusListener(): void {
    // Prüfe auf Updates, wenn die App in den Vordergrund kommt
    if (typeof window !== 'undefined') {
      fromEvent(window, 'focus')
        .pipe(concatMap(() => this.updates.checkForUpdate()))
        .subscribe();
    }
  }
}
