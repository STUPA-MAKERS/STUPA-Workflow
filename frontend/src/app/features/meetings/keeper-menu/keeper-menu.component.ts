import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Attendance, Meeting, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';

/** One member of the picker. */
interface Candidate {
  principalId: Uuid;
  name: string;
  /** "Anwesend · führt das Protokoll". */
  sub: string;
  current: boolean;
}

/**
 * The minute-taker menu of the dock (board Sitzung-Menues-B).
 *
 * A live meeting: the planned handover on top ("Lea Hoffmann übernimmt ab TOP 4",
 * "Verwerfen"), then "Protokollführung übergeben an" with a member search and the
 * members who can keep the minutes. A pick opens the handover dialog, which asks when the
 * handover takes effect. A planned meeting: "Protokollführung zuweisen"; a pick names the
 * minute-taker at once.
 *
 * O20: only members with the gremium right `protocol.write` ("Protokoll führen") are in
 * the list; the server refuses any other with 422.
 */
@Component({
  selector: 'app-keeper-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, IconComponent, AvatarComponent],
  templateUrl: './keeper-menu.component.html',
  styleUrl: './keeper-menu.component.scss',
  host: { '[class.km--sheet]': 'inSheet()' },
})
export class KeeperMenuComponent {
  private readonly i18n = inject(I18nService);

  readonly meeting = input.required<Meeting>();
  readonly attendance = input.required<Attendance[]>();
  /** In a bottom sheet (surface 2) the field and the hover go one step down from the menu (surface 3). */
  readonly inSheet = input(false);

  /** A member was picked: the new minute-taker, or the current one (no change). */
  readonly pick = output<Uuid>();
  /** Discard the planned handover. */
  readonly discard = output<void>();

  protected readonly query = signal('');

  protected readonly live = computed(() => this.meeting().status === 'live');
  protected readonly heading = computed<TranslationKey>(() =>
    this.live() ? 'meetings.keeper.handTo' : 'meetings.keeper.assign',
  );

  /** "übernimmt ab TOP 4", or "übernimmt mit dem nächsten TOP" without a known number. */
  protected readonly plannedSub = computed(() => {
    const plan = this.meeting().plannedHandover;
    if (!plan) return '';
    return plan.fromPosition !== null
      ? this.i18n.translate('meetings.keeper.takesOverAt', {
          top: this.i18n.translate('meetings.agenda.top', { n: plan.fromPosition }),
        })
      : this.i18n.translate('meetings.keeper.takesOverNext');
  });

  protected readonly candidates = computed<Candidate[]>(() => {
    const m = this.meeting();
    const q = this.query().trim().toLowerCase();
    return this.attendance()
      .filter((a) => a.canKeepProtocol)
      .filter((a) => !q || [a.displayName, a.email].some((v) => v?.toLowerCase().includes(q)))
      .map((a) => {
        const current = a.principalId === m.protokollantId;
        const state = this.i18n.translate(
          a.status ? `meetings.attendance.${a.status}` : 'meetings.attendance.unknown',
        );
        const sub = current ? `${state} · ${this.i18n.translate('meetings.keeper.keeps')}` : state;
        return { principalId: a.principalId, name: a.displayName || a.email || '—', sub, current };
      });
  });

  /** A pick of the current minute-taker keeps everything as it is; the dock just closes. */
  protected choose(c: Candidate): void {
    this.pick.emit(c.principalId);
  }
}
