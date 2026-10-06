import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  type Delegation,
  type DelegationRecipient,
  DelegationsApiService,
  type MeetingDelegationContext,
} from '@core/api/delegations.service';
import type { Attendance, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';

/** Above this many substitutes the dialog shows a search field. */
const SEARCH_ABOVE = 5;

/**
 * "Vertretung eintragen" (O6): during a live meeting the meeting lead names a substitute
 * for a missing member.
 *
 * The list has the substitutes from the pool of the gremium that apply to the member: the
 * personal entries for the member and the gremium-wide entries
 * (`GET /delegations/meetings/{id}/recipients?delegatorId=`). The server leaves out the
 * lead and the member. A pick plus "Vertretung eintragen" sends `POST /delegations` with
 * `delegatorId`. The vote goes with it by default, when the platform allows a vote
 * transfer.
 *
 * The ui-kit dialog is a centered dialog on a desktop and a bottom sheet on a phone. The
 * server checks every rule again (live, lead, missing, pool, no chains).
 */
@Component({
  selector: 'app-lead-substitute-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    AvatarComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SwitchComponent,
  ],
  templateUrl: './lead-substitute-dialog.component.html',
  styleUrl: './lead-substitute-dialog.component.scss',
})
export class LeadSubstituteDialogComponent {
  private readonly api = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly meetingId = input.required<Uuid>();
  /** The missing member; `null` closes the dialog. */
  readonly member = input<Attendance | null>(null);

  readonly closed = output<void>();
  readonly created = output<Delegation>();

  /** The pool substitutes of the member, or `null` while they load. */
  protected readonly pool = signal<DelegationRecipient[] | null>(null);
  protected readonly failed = signal(false);
  /** The gates of the meeting, or `null` while they load. */
  protected readonly context = signal<MeetingDelegationContext | null>(null);
  protected readonly selected = signal<Uuid | ''>('');
  protected readonly voting = signal(true);
  protected readonly query = signal('');
  protected readonly busy = signal(false);

  protected readonly open = computed(() => this.member() !== null);
  protected readonly memberName = computed(() => {
    const m = this.member();
    return m?.displayName || m?.email || '—';
  });
  protected readonly subtitle = computed(() =>
    this.i18n.translate('meetings.leadSubstitute.for', { name: this.memberName() }),
  );

  /** The gremium allows a delegation. Unknown counts as allowed: the server decides. */
  protected readonly allowed = computed(() => this.context()?.allowVoteDelegation ?? true);
  protected readonly votingEnabled = computed(() => this.context()?.votingDelegationEnabled ?? false);
  protected readonly searchable = computed(() => (this.pool()?.length ?? 0) > SEARCH_ABOVE);

  protected readonly shown = computed(() => {
    const needle = this.query().trim().toLowerCase();
    return (this.pool() ?? []).filter(
      (r) => !needle || (r.displayName ?? '').toLowerCase().includes(needle),
    );
  });

  protected readonly canSubmit = computed(
    () => this.selected() !== '' && this.allowed() && !this.busy(),
  );

  constructor() {
    // Each opening starts empty and loads the pool of that member.
    effect(() => {
      const m = this.member();
      const meetingId = this.meetingId();
      if (!m) return;
      untracked(() => this.load(meetingId, m.principalId));
    });
  }

  private load(meetingId: Uuid, memberId: Uuid): void {
    this.pool.set(null);
    this.failed.set(false);
    this.selected.set('');
    this.voting.set(true);
    this.query.set('');
    this.api.poolSubstitutes(meetingId, memberId).subscribe({
      next: (rows) => {
        if (this.member()?.principalId === memberId) this.pool.set(rows);
      },
      error: () => {
        if (this.member()?.principalId !== memberId) return;
        this.pool.set([]);
        this.failed.set(true);
      },
    });
    // A late answer for a member of an earlier opening must not reach the dialog that is
    // now open for another member.
    this.api.meetingContext(meetingId, { quiet: true }).subscribe({
      next: (c) => {
        if (this.member()?.principalId === memberId) this.context.set(c);
      },
      error: () => {
        if (this.member()?.principalId === memberId) this.context.set(null);
      },
    });
  }

  protected name(r: DelegationRecipient): string {
    return r.displayName || this.i18n.translate('common.unnamed');
  }

  protected submit(): void {
    const m = this.member();
    if (!m || !this.canSubmit()) return;
    this.busy.set(true);
    this.api
      .create({
        meetingId: this.meetingId(),
        delegatorId: m.principalId,
        delegateId: this.selected() as Uuid,
        delegateVoting: this.votingEnabled() && this.voting(),
      })
      .subscribe({
        next: (d) => {
          this.busy.set(false);
          this.toast.success(this.i18n.translate('meetings.leadSubstitute.created'));
          this.created.emit(d);
        },
        // The detail of the server is English; the toast keeps the language of the UI.
        error: () => {
          this.busy.set(false);
          this.toast.error(this.i18n.translate('meetings.leadSubstitute.failed'));
        },
      });
  }
}
