import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import {
  type Delegation,
  DelegationsApiService,
  type MeetingDelegationContext,
} from '@core/api/delegations.service';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { ButtonComponent, IconComponent, ToastService } from '@stupa-makers/ui-kit';
import { DelegationDialogComponent } from './delegation-dialog/delegation-dialog.component';

/** A change of the own delegation: a new one, or a revoked one with its delegator. */
export type DelegationCardChange = { kind: 'created' } | { kind: 'revoked'; delegation: Delegation };

/**
 * The own delegations of a meeting ("Vertretung").
 *
 * - `variant="section"`: a section of the attendance sheet, rows on surface 3.
 * - `variant="box"`: a box of the side column of the participant view (boards
 *   Teilnahme-Vorher and Teilnahme-Live).
 *
 * It shows the own outgoing delegation, which stays revocable until the meeting starts,
 * the setup with its deadline ("Einrichtbar bis Di., 13.10.2026, 17:00"), and the
 * delegations directed at me ("Du vertrittst Jonas Weber in dieser Sitzung."). The setup
 * opens `app-delegation-dialog`. The server enforces all rules: deadline, recipient set
 * and chains. The card only hides what is clearly invalid.
 */
@Component({
  selector: 'app-meeting-delegation-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    TranslatePipe,
    LocalizedDatePipe,
    AvatarComponent,
    ButtonComponent,
    IconComponent,
    DelegationDialogComponent,
  ],
  templateUrl: './meeting-delegation-card.component.html',
  styleUrl: './meeting-delegation-card.component.scss',
})
export class MeetingDelegationCardComponent {
  private readonly api = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly meetingId = input.required<Uuid>();
  readonly variant = input<'section' | 'box'>('section');
  /** The line below the title of the dialog: the meeting and its date. */
  readonly subtitle = input('');
  /** The own delegation changed. The attendance sheet then loads its delegations again. */
  readonly changed = output<DelegationCardChange>();
  /** The context of the meeting, after each load. The participant view reads it. */
  readonly contextChange = output<MeetingDelegationContext | null>();

  protected readonly ctx = signal<MeetingDelegationContext | null>(null);
  protected readonly dialogOpen = signal(false);
  protected readonly busy = signal(false);

  /** Show the card when delegation is active in the Gremium and relevant to me. */
  protected readonly visible = computed(() => {
    const c = this.ctx();
    if (!c || !c.allowVoteDelegation) return false;
    return c.canDelegate || c.myDelegation !== null || c.incoming.length > 0;
  });

  /** The setup is closed for good: the deadline passed and no substitute is left. */
  protected readonly deadlineRow = computed(() => {
    const c = this.ctx();
    return !!c && c.canDelegate && c.deadlinePassed && !c.meetingStarted && !this.canCreate();
  });

  /** The section has a row to show: the own delegation, the setup, the deadline or an incoming one. */
  protected readonly hasRows = computed(() => {
    const c = this.ctx();
    if (!c) return false;
    return c.myDelegation !== null || this.canCreate() || this.deadlineRow() || c.incoming.length > 0;
  });

  /** True when the user may delegate, the meeting is still planned and a window is
   *  open. A substitute stays usable until the meeting starts. Only `meetingStarted`
   *  blocks the setup hard. */
  protected readonly canCreate = computed(() => {
    const c = this.ctx();
    return Boolean(c && c.canDelegate && !c.meetingStarted && this.hasOpenWindow(c));
  });

  constructor() {
    effect(() => {
      const id = this.meetingId();
      this.ctx.set(null);
      this.api.meetingContext(id).subscribe({
        next: (c) => this.adopt(c),
        error: () => this.adopt(null),
      });
    });
  }

  /** After the deadline only substitutes stay allowed. The window counts as open while
   *  at least one selectable recipient remains. */
  private hasOpenWindow(c: MeetingDelegationContext): boolean {
    if (!c.deadlinePassed) return true;
    return c.recipients.some((r) => r.viaPool);
  }

  private adopt(c: MeetingDelegationContext | null): void {
    this.ctx.set(c);
    this.contextChange.emit(c);
  }

  protected openDialog(): void {
    this.dialogOpen.set(true);
  }

  protected created(): void {
    this.dialogOpen.set(false);
    this.reload();
    this.changed.emit({ kind: 'created' });
  }

  protected revoke(d: Delegation): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.api.revoke(d.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(this.i18n.translate('delegation.toast.revoked'));
        this.reload();
        this.changed.emit({ kind: 'revoked', delegation: d });
      },
      error: () => {
        this.busy.set(false);
        this.toast.error(this.i18n.translate('delegation.toast.revokeFailed'));
      },
    });
  }

  /** Load the context again, for example after a delegation changed somewhere else. */
  reload(): void {
    this.api.meetingContext(this.meetingId(), { quiet: true }).subscribe({
      next: (c) => this.adopt(c),
      error: () => {},
    });
  }
}
