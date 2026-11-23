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
import {
  TicketsApiService,
  type TicketArea,
  type TicketBlockedSender,
} from '@core/api/tickets.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import type { LoadState } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import {
  ButtonComponent,
  ButtonGroupComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  InputComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  ScreenGroupDirective,
  ScreenSkeletonDirective,
  SettingsScreenComponent,
  type SettingsGroup,
  type SettingsState,
} from '@stupa-makers/ui-kit/screens';
import { AdminApiService } from '../admin-api.service';
import type { HelpTicketsSettings } from '../admin.models';
import { personLabel } from '@shared/person-label.util';
import { type AreaGremium, TicketAreaDialogComponent } from './ticket-area-dialog.component';

/** The choices of the retention chip, in months. */
export const RETENTION_CHOICES: readonly number[] = [1, 3, 6, 12, 24, 36, 60, 120];
/** The retention that the switch turns on with when no earlier value is known. */
const DEFAULT_RETENTION = 12;

/** The keys of the rows of the group "Bereiche": one per Bereich, and "Bereich anlegen". */
const AREA_ROW = 'area:';
const AREA_NEW = 'area-new';

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
 * - `retentionMonths`: months after the close until the reporter is anonymized; the
 *   switch off sends `null` (never).
 *
 * "Speichern" (the floating button) and "Verwerfen" (in the header) show only while the
 * form has changes. "Verwerfen" puts the stored values back. The page shows the form only with
 * `admin.site` and not after a 403.
 *
 * "Bereiche": one row per Bereich of the tickets with its Gremium and its Kategorien,
 * then the row "Bereich anlegen". The dialog of a row changes the name, the Gremium whose roles give the work right
 * `ticket.work`, the switch "Neue Tickets per E-Mail" and the Kategorien, and deletes a
 * Bereich without a ticket. The Bereich "Plattform" is built in: its dialog holds only
 * the switch. A Bereich saves in its dialog at once, apart from "Speichern" of the form.
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
    FormsModule,
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    SettingsScreenComponent,
    ScreenGroupDirective,
    ScreenSkeletonDirective,
    FilterSelectComponent,
    ButtonComponent,
    ButtonGroupComponent,
    InputComponent,
    LoadStateComponent,
    SwitchComponent,
    TicketAreaDialogComponent,
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
  private readonly skelSwitches = [
    'admin.helpTickets.public',
    'admin.helpTickets.anonymize',
  ] as const;
  /** The last months value, so the switch turns on with it again. */
  private lastMonths = DEFAULT_RETENTION;

  /** The blocked senders need `ticket.manage`. The server checks it again. */
  protected readonly canBlock = computed(() => this.auth.can('ticket.manage'));

  /** The page needs the site right. The server checks it again. */
  protected readonly form: SettingsForm<HelpTicketsSettings, HelpTicketsSettings> = settingsForm<
    HelpTicketsSettings,
    HelpTicketsSettings,
    HelpTicketsSettings
  >({
    allowed: () => this.auth.can('admin.site'),
    load: () => this.api.getHelpTickets(),
    put: (body) => this.api.putHelpTickets(body),
    draftOf: (s) => ({ ...s }),
    initial: { wikiUrl: '', publicEnabled: false, retentionMonths: null },
    body: () => {
      const d = this.draft();
      return this.wikiError() ? null : { ...d, wikiUrl: d.wikiUrl.trim() };
    },
    dirty: (s) => {
      const d = this.draft();
      return (
        d.wikiUrl.trim() !== s.wikiUrl ||
        d.publicEnabled !== s.publicEnabled ||
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
    const values = new Set([...RETENTION_CHOICES, ...(current !== null ? [current] : [])]);
    return [...values]
      .sort((a, b) => a - b)
      .map((n) => ({ value: String(n), label: this.monthsText(n) }));
  });

  protected readonly dirty = this.form.dirty;

  /** The state of the settings screen (§ui-kit:002244); without a right the blocked senders stay. */
  protected readonly screenState = computed<SettingsState>(() => {
    switch (this.form.state()) {
      case 'loading':
        return { state: 'loading' };
      case 'forbidden':
        return {
          state: 'forbidden',
          message: this.canBlock() ? '' : this.i18n.translate('admin.helpTickets.forbidden'),
        };
      case 'error':
        return {
          state: 'error',
          message: this.i18n.translate('admin.helpTickets.loadError'),
          retry: () => this.form.reload(),
        };
      default:
        return { state: 'ready' };
    }
  });

  /** Wiki, Meldungen and Bereiche follow the form; the blocked senders have their own load state. */
  protected readonly groups = computed<SettingsGroup[]>(() => [
    { key: 'wiki', label: this.i18n.translate('admin.helpTickets.wiki'), rows: [] },
    {
      key: 'reports',
      label: this.i18n.translate('admin.helpTickets.reports'),
      rows: this.skelSwitches.map((key) => ({
        key,
        label: this.i18n.translate(key),
        control: 'switch' as const,
      })),
    },
    {
      key: 'areas',
      label: this.i18n.translate('admin.helpTickets.areas.title'),
      rows: [
        ...(this.areas() ?? []).map((a) => ({
          key: AREA_ROW + a.id,
          label: a.name,
          meta: this.areaParts(a).join(' · '),
          control: 'action' as const,
          action: { key: AREA_ROW + a.id, label: a.name, icon: 'edit' as const },
        })),
        {
          key: AREA_NEW,
          label: this.i18n.translate('admin.helpTickets.areas.create'),
          control: 'action' as const,
          action: {
            key: AREA_NEW,
            label: this.i18n.translate('admin.helpTickets.areas.create'),
            icon: 'plus' as const,
          },
        },
      ],
    },
    ...(this.canBlock()
      ? [
          {
            key: 'blocked',
            label: this.i18n.translate('admin.helpTickets.blocked'),
            rows: [],
            always: true,
          },
        ]
      : []),
  ]);

  /** null while loading; the read failed: `blockedError`. */
  protected readonly blocked = signal<TicketBlockedSender[] | null>(null);
  protected readonly blockedError = signal(false);
  protected readonly blockedState = computed<LoadState>(() =>
    this.blockedError() ? 'error' : this.blocked() === null ? 'loading' : 'ok',
  );
  /** The block whose unblock is in flight. */
  protected readonly unblocking = signal<string | null>(null);

  /** The Bereiche; null until the read ends. */
  protected readonly areas = signal<TicketArea[] | null>(null);
  /** The Gremien of the select in the dialog and of the row texts. */
  protected readonly gremien = signal<AreaGremium[]>([]);
  /** The open dialog: a Bereich to edit, `'new'` to create one, null: closed. */
  protected readonly editing = signal<TicketArea | 'new' | null>(null);
  protected readonly editingArea = computed(() => {
    const e = this.editing();
    return e === 'new' ? null : e;
  });

  constructor() {
    if (this.canBlock()) this.loadBlocked();
    if (this.auth.can('admin.site')) {
      this.loadAreas();
      this.api.listGremienOptions().subscribe({
        next: (list) => this.gremien.set(list.map((g) => ({ id: g.id, name: g.name }))),
        error: () => this.gremien.set([]),
      });
    }
  }

  private loadAreas(): void {
    this.tickets.adminAreas().subscribe({
      next: (list) => this.areas.set(list),
      error: () => {
        this.areas.set([]);
        this.toast.show(this.i18n.translate('admin.helpTickets.areas.error.load'), 'error');
      },
    });
  }

  /** A row of the group "Bereiche": a Bereich opens its dialog, the last row a new one. */
  protected onAreaAction(key: string): void {
    if (key === AREA_NEW) return this.editing.set('new');
    const area = (this.areas() ?? []).find((a) => AREA_ROW + a.id === key);
    if (area) this.editing.set(area);
  }

  /** The line under the name: the team, "In der App" with the switch, then the Kategorien. */
  protected areaParts(a: TicketArea): string[] {
    const gremium = this.gremien().find((g) => g.id === a.gremiumId)?.name;
    const team = a.platform
      ? this.i18n.translate('admin.helpTickets.areas.builtIn')
      : (gremium ?? this.i18n.translate('admin.helpTickets.areas.noGremium'));
    const inApp = !a.platform && a.inApp ? [this.i18n.translate('admin.helpTickets.areas.inAppShort')] : [];
    return [team, ...inApp, ...a.categories.map((c) => c.name)];
  }

  protected onAreaSaved(saved: TicketArea): void {
    const list = this.areas() ?? [];
    const known = list.some((a) => a.id === saved.id);
    this.areas.set(known ? list.map((a) => (a.id === saved.id ? saved : a)) : [...list, saved]);
    this.editing.set(null);
    this.toast.show(this.i18n.translate('admin.helpTickets.areas.saved'), 'success');
  }

  protected onAreaDeleted(gone: TicketArea): void {
    this.areas.update((list) => (list ?? []).filter((a) => a.id !== gone.id));
    this.editing.set(null);
    this.toast.show(this.i18n.translate('admin.helpTickets.areas.deleted'), 'success');
  }

  protected loadBlocked(): void {
    this.blocked.set(null);
    this.blockedError.set(false);
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
        this.toast.show(this.i18n.translate('admin.helpTickets.error.unblock'), 'error');
      },
    });
  }

  private dropBlock(b: TicketBlockedSender): void {
    const at = (this.blocked() ?? []).findIndex((x) => x.id === b.id);
    this.unblocking.set(null);
    this.blocked.update((list) => (list ?? []).filter((x) => x.id !== b.id));
    this.toast.show(this.i18n.translate('admin.helpTickets.unblocked'), 'success');
    afterNextRender(() => this.focusAfterUnblock(at), { injector: this.injector });
  }

  private focusAfterUnblock(at: number): void {
    const root = this.host.nativeElement;
    const buttons = Array.from(root.querySelectorAll<HTMLElement>('.ht__blocks button'));
    const next = buttons[Math.min(Math.max(at, 0), buttons.length - 1)];
    if (next) return next.focus();
    const section = root.querySelector('#ht-blocked')?.closest<HTMLElement>('[role="group"]');
    if (!section) return;
    section.setAttribute('tabindex', '-1');
    section.focus();
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
