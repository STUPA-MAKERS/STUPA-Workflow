import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { AgendaItem, Attendance, Meeting } from '@core/api/models';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';

/**
 * "Sitzung vorbereiten": what a planned meeting needs before it opens.
 *
 * Three cards: the agenda ("6 TOPs vorbereitet", "Tagesordnung bearbeiten"), the
 * minute-taker ("Zuweisen"; the opening needs one, so a missing one is marked) and the
 * attendance ("0 von 23 anwesend", "Erfassen"). Below them "Sitzung eröffnen", disabled
 * until a minute-taker is set.
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
  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  readonly attendance = input.required<Attendance[]>();

  /** Show the agenda: the pane on a wide screen, the agenda sheet below it. */
  readonly editAgenda = output<void>();
  /** Open the picker of the minute-taker. */
  readonly assignKeeper = output<void>();
  readonly recordAttendance = output<void>();
  readonly start = output<void>();

  protected readonly presentCount = computed(
    () => this.attendance().filter((a) => a.status === 'present').length,
  );
}
