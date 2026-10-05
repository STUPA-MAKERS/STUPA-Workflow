import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { NotificationPreference } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { NoteComponent } from '@shared/ui/note/note.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { SwitchComponent } from '@stupa-makers/ui-kit';

/**
 * Kinds that the page never shows. No mail goes out for them (F10): "vote" has no sender,
 * and "role_change" has no caller. The server catalogue does not list them any more; the
 * filter keeps an older server from showing a switch that does nothing.
 */
const HIDDEN_KINDS: ReadonlySet<string> = new Set(['vote', 'role_change']);

/**
 * Account page "Benachrichtigungen" (board Konto-Benachrichtigungen).
 *
 * One row per kind of the server catalogue: the label, one line that says when the mail
 * goes out, and a switch. Every kind is on by default; a switch is an opt-out. The
 * subtitle says that login links always go out, because the magic-link mails are
 * essential and have no switch.
 *
 * A switch saves at once and sends every switch in one PUT (the hidden kinds too, with
 * their stored value). When the save fails, the switch goes back and an error shows.
 */
@Component({
  selector: 'app-account-notifications',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NoteComponent, PageHeaderComponent, SkeletonComponent, SwitchComponent, TranslatePipe],
  templateUrl: './notifications.component.html',
  styleUrl: './notifications.component.scss',
})
export class AccountNotificationsComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);

  /** Every kind the server sent, the hidden ones included. */
  private readonly prefs = signal<NotificationPreference[]>([]);
  readonly loading = signal(true);
  readonly error = signal<TranslationKey | null>(null);

  /** The kinds that get a row. */
  readonly rows = computed(() => this.prefs().filter((p) => !HIDDEN_KINDS.has(p.kind)));

  constructor() {
    this.api.listNotificationPreferences().subscribe({
      next: (p) => {
        this.prefs.set(p);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('account.notifications.error');
        this.loading.set(false);
      },
    });
  }

  /** Flip one switch and save at once. The server returns the effective state. */
  toggle(kind: string, enabled: boolean): void {
    const before = this.prefs();
    const next = before.map((p) => (p.kind === kind ? { ...p, enabled } : p));
    this.prefs.set(next);
    this.error.set(null);
    this.api.setNotificationPreferences(next).subscribe({
      next: (saved) => this.prefs.set(saved),
      error: () => {
        this.prefs.set(before);
        this.error.set('account.notifications.saveError');
      },
    });
  }

  protected kindLabel(kind: string): string {
    return this.lookup(`account.notifications.kind.${kind}`, kind);
  }

  protected kindHint(kind: string): string {
    return this.lookup(`account.notifications.hint.${kind}`, '');
  }

  /** Translate a key. A new kind with no translation shows the fallback, not the key. */
  private lookup(key: string, fallback: string): string {
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? fallback : label;
  }
}
