import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';

/**
 * Account calendar subscription page.
 *
 * The page shows the personal iCal feed URL to copy. The feed holds the meetings of the
 * Gremien of the user. The user can rotate the URL, which invalidates the old one. The
 * server creates the feed token only on the first "generate" action. Until then `url`
 * is null.
 */
@Component({
  selector: 'app-account-calendar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SkeletonComponent, TranslatePipe, ButtonComponent, PageHeaderComponent],
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

  /** Generate a new feed token. This invalidates the previous URL. */
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

  /** Copy the subscription URL to the clipboard. The Clipboard API can be absent. */
  copy(): void {
    const url = this.url();
    if (!url) return;
    void navigator.clipboard?.writeText(url)?.then(
      () => this.copied.set(true),
      () => this.copied.set(false),
    );
  }
}
