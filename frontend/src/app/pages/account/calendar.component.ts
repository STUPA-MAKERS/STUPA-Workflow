import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent } from '@shared/ui';

/**
 * Konto → Kalender-Abo (#ics): zeigt die persönliche iCal-Feed-URL (Sitzungen der
 * eigenen Gremien) zum Kopieren und erlaubt das Rotieren (alte URL wird ungültig).
 * Der Feed-Token entsteht erst beim ersten »Erzeugen« — bis dahin ist `url` null.
 */
@Component({
  selector: 'app-account-calendar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent],
  templateUrl: './calendar.component.html',
  styleUrl: './calendar.component.scss',
})
export class AccountCalendarComponent {
  private readonly api = inject(ApiClient);

  readonly url = signal<string | null>(null);
  readonly loading = signal(true);
  readonly error = signal(false);
  readonly busy = signal(false);
  readonly copied = signal(false);

  constructor() {
    this.api.myCalendar().subscribe({
      next: (feed) => {
        this.url.set(feed.url);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Feed-Token (neu) erzeugen — invalidiert die bisherige URL. */
  rotate(): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(false);
    this.copied.set(false);
    this.api.rotateCalendar().subscribe({
      next: (feed) => {
        this.url.set(feed.url);
        this.busy.set(false);
      },
      error: () => {
        this.error.set(true);
        this.busy.set(false);
      },
    });
  }

  /** Abo-URL in die Zwischenablage kopieren (best-effort; Clipboard-API optional). */
  copy(): void {
    const url = this.url();
    if (!url) return;
    void navigator.clipboard?.writeText(url)?.then(
      () => this.copied.set(true),
      () => this.copied.set(false),
    );
  }
}
