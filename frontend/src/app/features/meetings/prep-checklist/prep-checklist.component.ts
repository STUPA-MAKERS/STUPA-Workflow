import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { AgendaItem, Attendance, Meeting } from '@core/api/models';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { openWindowClock, openWindowState, openWindowWhen } from '../open-window.util';

/**
 * "Sitzung vorbereiten": what a planned meeting needs before it opens.
 *
 * Up to three cards: the agenda ("6 TOPs vorbereitet", "Tagesordnung bearbeiten"; only
 * where the page shows no agenda pane beside it), the minute-taker ("Zuweisen"; the opening needs one, so a missing one is marked) and the
 * attendance ("0 von 23 anwesend", "Erfassen"). Below them "Sitzung eröffnen", disabled
 * until a minute-taker is set and until the open window of the meeting opens
 * ("Eröffnen ab 17:00").
 */
@Component({
  selector: 'app-prep-checklist',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, IconComponent],
  templateUrl: './prep-checklist.component.html',
  styleUrl: './prep-checklist.component.scss',
})
export class PrepChecklistComponent {
  private readonly i18n = inject(I18nService);
  private readonly now = openWindowClock();

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  readonly attendance = input.required<Attendance[]>();
  /** Show the agenda card. A wide page shows the agenda pane, so the card would repeat it. */
  readonly agendaCard = input(true);

  /** Open the agenda sheet. */
  readonly editAgenda = output<void>();
  /** Open the picker of the minute-taker. */
  readonly assignKeeper = output<void>();
  readonly recordAttendance = output<void>();
  readonly start = output<void>();

  /** "Eröffnen ab 17:00" while the open window is not open yet, else `''`. */
  protected readonly opensAtText = computed(() => {
    const m = this.meeting();
    if (!m.opensAt || openWindowState(m, this.now()) !== 'tooEarly') return '';
    const when = openWindowWhen(m.opensAt, this.now(), this.i18n.locale());
    return this.i18n.translate('meetings.control.opensAt', { when });
  });

  protected readonly presentCount = computed(
    () => this.attendance().filter((a) => a.status === 'present').length,
  );
}
