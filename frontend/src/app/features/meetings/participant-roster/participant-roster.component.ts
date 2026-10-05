import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { Attendance, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { StatusKind } from '@shared/status-kind.util';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { memberAttendanceKey } from '../meetings-display.util';

let nextId = 0;

/** One row of the roster. */
interface RosterRow {
  id: Uuid;
  name: string;
  self: boolean;
  keeper: boolean;
  kind: StatusKind;
  key: TranslationKey;
}

/**
 * The attendance of all members, read only, for the participant view: "Anwesenheit ·
 * 12 von 19 anwesend" and one row per member with the name and "Anwesend", "Abwesend"
 * or "Offen". The row of the minute-taker says so.
 *
 * A member sees "Anwesend" and "Abwesend" only (Z2): an excuse and an absence look the
 * same. The roster never shows a reason; the server gives it only to the member and to
 * the meeting lead.
 */
@Component({
  selector: 'app-participant-roster',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, AvatarComponent, StatusTextComponent],
  templateUrl: './participant-roster.component.html',
  styleUrl: './participant-roster.component.scss',
})
export class ParticipantRosterComponent {
  private readonly i18n = inject(I18nService);
  protected readonly capId = `pr-cap-${nextId++}`;

  readonly rows = input.required<readonly Attendance[]>();
  /** The minute-taker of the meeting, or `null`. */
  readonly protokollantId = input<Uuid | null>(null);

  protected readonly view = computed<RosterRow[]>(() =>
    this.rows().map((a) => {
      const status = a.status;
      return {
        id: a.principalId,
        name: a.displayName || a.email || this.i18n.translate('participant.delegation.unnamed'),
        self: a.isSelf,
        keeper: a.principalId === this.protokollantId(),
        kind: status === 'present' ? 'accent' : status ? 'neutral' : 'muted',
        key: status ? memberAttendanceKey(status) : 'meetings.attendance.unknown',
      };
    }),
  );

  protected readonly present = computed(
    () => this.rows().filter((a) => a.status === 'present').length,
  );
}
