import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { NotificationPreference } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { EmptyStateComponent, NoteComponent, SkeletonComponent, SwitchComponent } from '@stupa-makers/ui-kit';

/**
 * Kinds that the page never shows. No mail goes out for them (F10): "vote" has no sender,
 * and "role_change" has no caller. The server catalogue does not list them any more; the
 * filter keeps an older server from showing a switch that does nothing.
 */
const HIDDEN_KINDS: ReadonlySet<string> = new Set(['vote', 'role_change']);

/**
 * Kinds that only reach the team that works on tickets. The page shows them only to a
 * holder of `ticket.manage`, because nobody else gets these mails.
 */
const TEAM_KINDS: ReadonlyMap<string, string> = new Map([
  ['ticket_created', 'ticket.manage'],
  ['ticket_message', 'ticket.manage'],
]);

/**
 * Account page "Benachrichtigungen" (board Konto-Benachrichtigungen).
 *
 * One row per kind of the server catalogue: the label, one line that says when the mail
 * goes out, and a switch. Every kind is on by default; a switch is an opt-out. The
 * subtitle says that login links always go out, because the magic-link mails are
 * essential and have no switch.
 *
 * A switch saves at once and sends every switch in one PUT (the hidden kinds too, with
 * their stored value). Only one PUT runs at a time: a switch that flips during a PUT
 * shows at once, and one more PUT with the latest state follows when the running one
 * ends. When a save fails, every switch goes back to the last state that the server
 * confirmed and an error shows. Thus the page and the server always agree after a save.
 */
@Component({
  selector: 'app-account-notifications',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmptyStateComponent, NoteComponent, PageHeaderComponent, SkeletonComponent, SwitchComponent, TranslatePipe],
  templateUrl: './notifications.component.html',
  styleUrl: './notifications.component.scss',
})
export class AccountNotificationsComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);

  /** Every kind the server sent, the hidden ones included. */
  private readonly prefs = signal<NotificationPreference[]>([]);
  readonly loading = signal(true);
  readonly error = signal<TranslationKey | null>(null);

  /** The last state that the server sent or confirmed. A failed save goes back to it. */
  private confirmed: NotificationPreference[] = [];
  /** A PUT runs. */
  private saving = false;
  /** A switch flipped while a PUT ran: send the latest state when the PUT ends. */
  private dirty = false;

  /** The kinds that get a row. */
  readonly rows = computed(() =>
    this.prefs().filter((p) => !HIDDEN_KINDS.has(p.kind) && this.mayGet(p.kind)),
  );

  /** A team kind shows only to the holders of its permission. */
  private mayGet(kind: string): boolean {
    const permission = TEAM_KINDS.get(kind);
    return permission === undefined || this.auth.can(permission);
  }

  constructor() {
    this.api.listNotificationPreferences().subscribe({
      next: (p) => {
        this.confirmed = p;
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
    this.prefs.update((all) => all.map((p) => (p.kind === kind ? { ...p, enabled } : p)));
    this.error.set(null);
    this.save();
  }

  /**
   * Send the current state. While a PUT runs, only mark the state as dirty; the running
   * PUT then sends it when it ends.
   */
  private save(): void {
    if (this.saving) {
      this.dirty = true;
      return;
    }
    this.saving = true;
    this.dirty = false;
    this.api.setNotificationPreferences(this.prefs()).subscribe({
      next: (saved) => {
        this.saving = false;
        this.confirmed = saved;
        // A switch flipped during the PUT: keep it on screen and send it now.
        if (this.dirty) this.save();
        else this.prefs.set(saved);
      },
      error: () => {
        this.saving = false;
        this.dirty = false;
        this.prefs.set(this.confirmed);
        this.error.set('account.notifications.saveError');
      },
    });
  }

  protected kindLabel(kind: string): string {
    return this.lookup(`account.notifications.kind.${kind}`, kind);
  }

  /** Translate a key. A new kind with no translation shows the fallback, not the key. */
  private lookup(key: string, fallback: string): string {
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? fallback : label;
  }
}
