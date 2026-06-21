import { Injectable, inject } from '@angular/core';
import { SwUpdate, type VersionReadyEvent } from '@angular/service-worker';
import { filter } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';

/**
 * PWA-Update-Fluss (#5): meldet sich der Service Worker mit einer neuen
 * App-Version (`VERSION_READY`), wird sie aktiviert und ein dauerhafter Toast
 * weist auf das nötige Neuladen hin. Ohne SW (Dev-Modus, alte Browser) ist
 * `isEnabled` false und nichts passiert.
 */
@Injectable({ providedIn: 'root' })
export class SwUpdateService {
  private readonly updates = inject(SwUpdate);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  init(): void {
    if (!this.updates.isEnabled) return;
    this.updates.versionUpdates
      .pipe(filter((e): e is VersionReadyEvent => e.type === 'VERSION_READY'))
      .subscribe(() => {
        void this.updates.activateUpdate().then(() => {
          this.toast.show(this.i18n.translate('pwa.updateReady'), 'info', 0);
        });
      });
  }
}
