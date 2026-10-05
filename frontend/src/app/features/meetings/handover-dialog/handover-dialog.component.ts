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
import type { AgendaItem, Attendance, HandoverMode, Meeting } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, DialogComponent, IconComponent } from '@stupa-makers/ui-kit';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { clockTime } from '../meetings-display.util';
import { currentPosition, handoverPreview } from '../keepers.util';

/** One choice of the handover time. */
interface ModeOption {
  mode: HandoverMode;
  label: string;
  sub: string;
  disabled: boolean;
}

/**
 * "Protokollführung übergeben" (board Sitzung-Protokoll-Uebergabe, Z3, O1).
 *
 * The dialog shows the current and the new minute-taker ("Bisher" → "Neu", "Ändern" goes
 * back to the picker), the time of the handover and the keeper line of the protocol head
 * after the handover.
 *
 * - "Ab jetzt" (`now`): the new person writes from this moment, in the current TOP.
 * - "Ab TOP n+1" (`next_item`): the current person finishes the current TOP; the handover
 *   takes effect with the next TOP. The last TOP has no next one (409 `no_next_item`).
 *
 * The server refuses a member without `protocol.write` (422
 * `protokollant_needs_protocol_write`, O20). The dialog shows a refusal in its body.
 *
 * The dialog asks only. `MeetingDialogsService.handOver` saves the open text first and
 * sends the handover; it reports `saving` and the `refusal` code back.
 */
@Component({
  selector: 'app-handover-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DialogComponent, ButtonComponent, IconComponent, AvatarComponent],
  templateUrl: './handover-dialog.component.html',
  styleUrl: './handover-dialog.component.scss',
})
export class HandoverDialogComponent {
  private readonly i18n = inject(I18nService);

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  /** The new minute-taker. The dialog is open while it is set. */
  readonly target = input<Attendance | null>(null);
  /** The handover request runs. */
  readonly saving = input(false);
  /**
   * The `code` of the last refusal of the server: `protokollant_needs_protocol_write`
   * (422), `no_next_item` or `already_protokollant` (409), else `null`.
   */
  readonly refusal = input<string | null>(null);

  readonly closed = output<void>();
  /** "Ändern": pick another member. */
  readonly repick = output<void>();
  /** "Übergeben" in the chosen mode. */
  readonly confirm = output<HandoverMode>();

  protected readonly mode = signal<HandoverMode>('now');
  /** The time of the handover "now", taken when the dialog opens. */
  protected readonly now = signal(new Date());

  constructor() {
    effect(() => {
      if (this.target()) {
        untracked(() => {
          this.mode.set('now');
          this.now.set(new Date());
        });
      }
    });
    // The server said the current TOP is the last one: only "now" is left.
    effect(() => {
      if (this.refusal() === 'no_next_item') untracked(() => this.mode.set('now'));
    });
  }

  /** The refusal as a sentence of the body. */
  protected readonly refusalKey = computed<TranslationKey | null>(() => {
    switch (this.refusal()) {
      case 'protokollant_needs_protocol_write':
        return 'meetings.toast.needsProtocolWrite';
      case 'no_next_item':
        return 'meetings.handover.noNextItem';
      case 'already_protokollant':
        return 'meetings.handoverDialog.already';
      default:
        return null;
    }
  });

  protected readonly open = computed(() => this.target() !== null);
  protected readonly targetName = computed(() => {
    const a = this.target();
    return a ? a.displayName || a.email || '—' : '';
  });
  protected readonly currentName = computed(() => this.meeting().protokollantName ?? '—');

  /** The 1-based number of the TOP that runs now, or `null`. */
  private readonly position = computed(() => currentPosition(this.meeting(), this.agenda()));

  /** The current TOP is the last one: no handover with the next TOP. */
  private readonly lastTop = computed(() => {
    const count = this.agenda().length;
    const pos = this.position();
    return this.refusal() === 'no_next_item' || count === 0 || (pos !== null && pos >= count);
  });

  protected readonly options = computed<ModeOption[]>(() => {
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    const pos = this.position();
    const time = clockTime(this.now().toISOString(), this.i18n.locale());
    const top = (n: number) => t('meetings.agenda.top', { n });
    const last = this.lastTop();
    return [
      {
        mode: 'now',
        label: t('meetings.handover.now'),
        sub: pos !== null
          ? t('meetings.handoverDialog.nowIn', { top: top(pos), time })
          : t('meetings.handoverDialog.nowAt', { time }),
        disabled: false,
      },
      {
        mode: 'next_item',
        label: pos !== null && !last
          ? t('meetings.handoverDialog.fromTop', { top: top(pos + 1) })
          : t('meetings.handover.nextItem'),
        sub: last
          ? t('meetings.handover.noNextItem')
          : pos !== null
            ? t('meetings.handoverDialog.finishes', { name: this.currentName(), top: top(pos) })
            : t('meetings.handoverDialog.withNext'),
        disabled: last,
      },
    ];
  });

  /** The keeper line of the protocol head after the handover. */
  protected readonly preview = computed(() => {
    const a = this.target();
    if (!a) return '';
    return handoverPreview(
      this.meeting(),
      this.agenda(),
      { principalId: a.principalId, name: this.targetName() },
      this.mode(),
      this.now(),
      (key, params) => this.i18n.translate(key, params),
      this.i18n.locale(),
    );
  });

  /** A disabled option takes no change event, so a pick is always possible here. */
  protected pickMode(option: ModeOption): void {
    this.mode.set(option.mode);
  }

  protected cancel(): void {
    this.closed.emit();
  }

  protected submit(): void {
    if (!this.target() || this.saving()) return;
    this.confirm.emit(this.lastTop() ? 'now' : this.mode());
  }
}
