import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TicketsApiService, type TicketBlockedSender } from '@core/api/tickets.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import {
  ButtonComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  InputComponent,
  NoteComponent,
  SwitchComponent,
  ToastService,
  FabComponent,
  PageHeaderComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { AdminApiService } from '../admin-api.service';
import type { HelpTicketsSettings } from '../admin.models';
import { personLabel } from '@shared/person-label.util';

/** The choices of the retention chip, in months. */
export const RETENTION_CHOICES: readonly number[] = [1, 3, 6, 12, 24, 36, 60, 120];
/** The retention that the switch turns on with when no earlier value is known. */
const DEFAULT_RETENTION = 12;

/** An absolute http(s) URL. */
export function isHttpUrl(text: string): boolean {
  try {
    const url = new URL(text.trim());
    return (url.protocol === 'http:' || url.protocol === 'https:') && !!url.hostname;
  } catch {
    return false;
  }
}

/**
 * "Hilfe & Tickets" (permission `admin.site`): where the help menu leads and how
 * reports are handled.
 *
 * `GET/PUT /admin/help-tickets` saves directly, without the draft of the branding:
 *
 * - `wikiUrl`: the handbook link of the help menu, http(s) only.
 * - `publicEnabled`: visitors without an account may report (e-mail and ALTCHA).
 * - `notifyNew`: a new ticket mails the holders of `ticket.manage`.
 * - `retentionMonths`: months after the close until the reporter is anonymized; the
 *   switch off sends `null` (never).
 *
 * "Speichern" (the floating button) and "Verwerfen" (in the header) show only while the
 * form has changes. "Verwerfen" puts the stored values back. The page shows the form only with
 * `admin.site` and not after a 403.
 *
 * "Gesperrte Absender" (with `ticket.manage`): one row per block of "Absender sperren"
 * on a ticket, with the date, the source ticket, the reports held back, and
 * "Entsperren".
 */
@Component({
  selector: 'app-help-tickets',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    EmptyStateComponent,
    FabComponent,
    FormsModule,
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    PageHeaderComponent,
    BreadcrumbsComponent,
    FilterSelectComponent,
    ButtonComponent,
    InputComponent,
    LoadStateComponent,
    NoteComponent,
    SwitchComponent,
  ],
  templateUrl: './help-tickets.component.html',
  styleUrl: './help-tickets.component.scss',
})
export class HelpTicketsComponent {
  private readonly api = inject(AdminApiService);
  private readonly tickets = inject(TicketsApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly injector = inject(Injector);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** The labels of the switch rows, which the loading form shows as they are. */
  protected readonly skelSwitches = [
    'admin.helpTickets.public',
    'admin.helpTickets.notify',
    'admin.helpTickets.anonymize',
  ] as const;
  /** The last months value, so the switch turns on with it again. */
  private lastMonths = DEFAULT_RETENTION;

  /** The blocked senders need `ticket.manage`. The server checks it again. */
  protected readonly canBlock = computed(() => this.auth.can('ticket.manage'));

  /** The page needs the site right. The server checks it again. */
  protected readonly form: SettingsForm<HelpTicketsSettings, HelpTicketsSettings> = settingsForm<HelpTicketsSettings, HelpTicketsSettings, HelpTicketsSettings>({
    allowed: () => this.auth.can('admin.site'),
    load: () => this.api.getHelpTickets(),
    put: (body) => this.api.putHelpTickets(body),
    draftOf: (s) => ({ ...s }),
    initial: { wikiUrl: '', publicEnabled: false, notifyNew: false, retentionMonths: null },
    body: () => {
      const d = this.draft();
      return this.wikiError() ? null : { ...d, wikiUrl: d.wikiUrl.trim() };
    },
    dirty: (s) => {
      const d = this.draft();
      return (
        d.wikiUrl.trim() !== s.wikiUrl ||
        d.publicEnabled !== s.publicEnabled ||
        d.notifyNew !== s.notifyNew ||
        d.retentionMonths !== s.retentionMonths
      );
    },
    onApply: (s) => {
      if (s.retentionMonths !== null) this.lastMonths = s.retentionMonths;
    },
  });
  protected readonly saving = this.form.saving;
  protected readonly draft = this.form.draft;

  protected readonly wikiError = computed(() =>
    isHttpUrl(this.draft().wikiUrl) ? '' : this.i18n.translate('admin.helpTickets.wikiInvalid'),
  );

  protected readonly monthOptions = computed<FilterSelectOption[]>(() => {
    const current = this.draft().retentionMonths;
    const values = new Set(RETENTION_CHOICES);
    if (current !== null) values.add(current);
    return [...values]
      .sort((a, b) => a - b)
      .map((n) => ({ value: String(n), label: this.monthsText(n) }));
  });

  protected readonly dirty = this.form.dirty;

  /** null while loading; the read failed: `blockedError`. */
  protected readonly blocked = signal<TicketBlockedSender[] | null>(null);
  protected readonly blockedError = signal(false);
  /** The block whose unblock is in flight. */
  protected readonly unblocking = signal<string | null>(null);

  constructor() {
    if (this.canBlock()) this.loadBlocked();
  }

  private loadBlocked(): void {
    this.tickets.blockedSenders().subscribe({
      next: (list) => {
        this.blockedError.set(false);
        this.blocked.set(list);
      },
      error: () => {
        this.blocked.set([]);
        this.blockedError.set(true);
      },
    });
  }

  /** The person, else the address. */
  protected senderName(b: TicketBlockedSender): string {
    if (b.kind === 'principal' && b.person) {
      return personLabel({ displayName: b.person.displayName, email: b.email }, this.i18n, {
        fallback: 'chat.deletedPerson',
      });
    }
    return b.email ?? '';
  }

  protected hits(b: TicketBlockedSender): string {
    return b.hitCount === 1
      ? this.i18n.translate('admin.helpTickets.blockedHits.one')
      : this.i18n.translate('admin.helpTickets.blockedHits.other', { count: b.hitCount });
  }

  /**
   * The row and its focused button leave the DOM, so the focus goes to the unblock
   * button of the row that takes its place (or the one before), else to the heading.
   * A 404 says the block is gone already (lifted from the ticket or by another manager),
   * so the row leaves as on a success.
   */
  protected unblock(b: TicketBlockedSender): void {
    if (this.unblocking()) return;
    this.unblocking.set(b.id);
    this.tickets.deleteBlockedSender(b.id).subscribe({
      next: () => this.dropBlock(b),
      error: (err: { status?: number }) => {
        if (err.status === 404) {
          this.dropBlock(b);
          return;
        }
        this.unblocking.set(null);
        this.toast.error(this.i18n.translate('admin.helpTickets.error.unblock'));
      },
    });
  }

  private dropBlock(b: TicketBlockedSender): void {
    const at = (this.blocked() ?? []).findIndex((x) => x.id === b.id);
    this.unblocking.set(null);
    this.blocked.update((list) => (list ?? []).filter((x) => x.id !== b.id));
    this.toast.success(this.i18n.translate('admin.helpTickets.unblocked'));
    afterNextRender(() => this.focusAfterUnblock(at), { injector: this.injector });
  }

  private focusAfterUnblock(at: number): void {
    const root = this.host.nativeElement;
    const buttons = Array.from(root.querySelectorAll<HTMLElement>('.ht__blocks button'));
    const next = buttons[Math.min(Math.max(at, 0), buttons.length - 1)];
    (next ?? root.querySelector<HTMLElement>('#ht-blocked'))?.focus();
  }

  protected monthsText(n: number): string {
    return n === 1
      ? this.i18n.translate('admin.helpTickets.afterOne')
      : this.i18n.translate('admin.helpTickets.after', { n });
  }

  protected patch(change: Partial<HelpTicketsSettings>): void {
    this.form.patch(change);
  }

  protected setAnonymize(on: boolean): void {
    this.patch({ retentionMonths: on ? this.lastMonths : null });
  }

  protected setMonths(value: string): void {
    const n = Number(value);
    this.lastMonths = n;
    this.patch({ retentionMonths: n });
  }

  protected discard(): void {
    this.form.reset();
  }

  protected save(): void {
    this.form.save();
  }
}
