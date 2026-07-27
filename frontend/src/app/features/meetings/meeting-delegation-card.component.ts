import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subject, debounceTime, distinctUntilChanged, switchMap } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  type Delegation,
  type DelegationRecipient,
  DelegationsApiService,
  type MeetingDelegationContext,
} from '@core/api/delegations.service';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CardComponent,
  CheckboxComponent,
  DialogComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';

/**
 * Delegation card on the meeting page.
 *
 * The card shows the own outgoing delegation, which stays revocable until the
 * meeting starts, and the delegations directed at me. The setup dialog picks the
 * recipient from the Gremium members and the substitute pool. It also runs a
 * server-side name search when external recipients are enabled. The server enforces
 * all rules: deadline, recipient set and chains. The card only hides what is
 * clearly invalid.
 */
@Component({
  selector: 'app-meeting-delegation-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    CheckboxComponent,
    DialogComponent,
    SelectComponent,
  ],
  templateUrl: './meeting-delegation-card.component.html',
  styleUrl: './meeting-delegation-card.component.scss',
})
export class MeetingDelegationCardComponent {
  private readonly api = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly meetingId = input.required<Uuid>();

  protected readonly ctx = signal<MeetingDelegationContext | null>(null);
  protected readonly dialogOpen = signal(false);
  protected readonly busy = signal(false);
  protected readonly delegateId = signal<Uuid | ''>('');
  protected readonly delegateVoting = signal(false);
  protected readonly query = signal('');
  /** Results of the server-side name search. It runs only when externals are enabled. */
  protected readonly searched = signal<DelegationRecipient[] | null>(null);
  private readonly query$ = new Subject<string>();

  /** Show the card when delegation is active in the Gremium and relevant to me. */
  protected readonly visible = computed(() => {
    const c = this.ctx();
    if (!c || !c.allowVoteDelegation) return false;
    return c.canDelegate || c.myDelegation !== null || c.incoming.length > 0;
  });

  /** True when the user may delegate, the meeting is still planned and a window is
   *  open. A pool recipient stays usable until the meeting starts. Only
   *  `meetingStarted` blocks the setup hard. */
  protected readonly canCreate = computed(() => {
    const c = this.ctx();
    return Boolean(c && c.canDelegate && !c.meetingStarted && this.hasOpenWindow(c));
  });

  protected readonly recipientOptions = computed<SelectOption[]>(() => {
    const c = this.ctx();
    const list = this.searched() ?? c?.recipients ?? [];
    const pool = this.i18n.translate('delegation.dialog.poolSuffix');
    return list.map((r) => ({
      value: r.principalId,
      label: (r.displayName || r.principalId) + (r.viaPool ? ` ${pool}` : ''),
    }));
  });

  protected readonly selectedRecipient = computed<DelegationRecipient | null>(() => {
    const id = this.delegateId();
    const list = this.searched() ?? this.ctx()?.recipients ?? [];
    return list.find((r) => r.principalId === id) ?? null;
  });

  constructor() {
    effect(() => {
      const id = this.meetingId();
      this.ctx.set(null);
      this.api.meetingContext(id).subscribe({
        next: (c) => this.ctx.set(c),
        error: () => this.ctx.set(null),
      });
    });
    this.query$
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        switchMap((q) => this.api.recipients(this.meetingId(), q)),
        takeUntilDestroyed(),
      )
      .subscribe((list) => this.searched.set(list));
  }

  /** After the deadline only pool recipients stay allowed. The window counts as open
   *  while at least one selectable recipient remains. */
  private hasOpenWindow(c: MeetingDelegationContext): boolean {
    if (!c.deadlinePassed) return true;
    return c.recipients.some((r) => r.viaPool);
  }

  protected openDialog(): void {
    this.delegateId.set('');
    this.delegateVoting.set(false);
    this.query.set('');
    this.searched.set(null);
    this.dialogOpen.set(true);
  }

  protected search(q: string): void {
    this.query.set(q);
    this.query$.next(q);
  }

  protected create(): void {
    const id = this.delegateId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.api
      .create({ meetingId: this.meetingId(), delegateId: id, delegateVoting: this.delegateVoting() })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.dialogOpen.set(false);
          this.toast.success(this.i18n.translate('delegation.toast.created'));
          this.reload();
        },
        error: (err: { error?: { detail?: string } }) => {
          this.busy.set(false);
          this.toast.error(err.error?.detail ?? this.i18n.translate('delegation.toast.createFailed'));
        },
      });
  }

  protected revoke(d: Delegation): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.api.revoke(d.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(this.i18n.translate('delegation.toast.revoked'));
        this.reload();
      },
      error: () => {
        this.busy.set(false);
        this.toast.error(this.i18n.translate('delegation.toast.revokeFailed'));
      },
    });
  }

  private reload(): void {
    this.api.meetingContext(this.meetingId(), { quiet: true }).subscribe({
      next: (c) => this.ctx.set(c),
      error: () => {},
    });
  }
}
