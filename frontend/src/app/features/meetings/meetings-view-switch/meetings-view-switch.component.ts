import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { SegmentedComponent, type SegmentedOption } from '@stupa-makers/ui-kit';
import type { MeetingsView } from '../meetings-overview.util';

/**
 * The switch "Liste | Kalender" in the header of the meeting overview. Both views show
 * it at the same place after the title; a phone has no calendar and no switch.
 */
@Component({
  selector: 'app-meetings-view-switch',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SegmentedComponent],
  templateUrl: './meetings-view-switch.component.html',
  styleUrl: './meetings-view-switch.component.scss',
})
export class MeetingsViewSwitchComponent {
  private readonly i18n = inject(I18nService);

  readonly value = input.required<MeetingsView>();
  readonly valueChange = output<MeetingsView>();

  protected readonly label = computed(() => this.i18n.translate('meetings.overview.view'));
  protected readonly options = computed<SegmentedOption[]>(() => [
    { value: 'list', label: this.i18n.translate('meetings.overview.viewList') },
    { value: 'calendar', label: this.i18n.translate('meetings.overview.viewCalendar') },
  ]);

  protected pick(value: string | null): void {
    if (value === 'list' || value === 'calendar') this.valueChange.emit(value);
  }
}
