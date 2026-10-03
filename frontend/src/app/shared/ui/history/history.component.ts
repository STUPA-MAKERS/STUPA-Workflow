import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import type { StatusKind } from '../../status-kind.util';
import { StatusTextComponent } from '../status-text/status-text.component';

/** One event of a history. */
export interface HistoryEntry {
  /** When it happened (ISO 8601). */
  at: string;
  icon: IconName;
  /** What happened: the new status, or the event ("Version 2 gespeichert"). */
  title: string;
  /** The colour of a status title. Leave it out for an event that is not a status. */
  kind?: StatusKind | null;
  /** Who did it: a person, or the gremium for the applicant (O16). */
  actor?: string | null;
  /** One more line, for example the transition ("Übergang „Prüfung beginnen“"). */
  body?: string | null;
}

interface HistoryDay {
  key: string;
  label: string;
  entries: (HistoryEntry & { meta: string })[];
}

let nextId = 0;

/**
 * A history, grouped by day: newest day first, and in each day the newest event first.
 *
 * A status title takes its colour (`kind`); any other event stays in the text colour.
 * The meta line gives the actor and the time. Each day is a list, named by its date.
 */
@Component({
  selector: 'app-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, StatusTextComponent],
  templateUrl: './history.component.html',
  styleUrl: './history.component.scss',
})
export class HistoryComponent {
  private readonly i18n = inject(I18nService);

  readonly entries = input.required<readonly HistoryEntry[]>();
  /** The surface of the rows; see `app-field-group`. */
  readonly surface = input<1 | 2 | 3>(2);

  protected readonly id = `history-${nextId++}`;

  protected readonly days = computed<HistoryDay[]>(() => {
    const locale = this.i18n.formatLocale();
    const thisYear = new Date().getFullYear();
    const time = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' });
    const sorted = [...this.entries()]
      .map((e) => ({ e, d: new Date(e.at) }))
      .sort((a, b) => b.d.getTime() - a.d.getTime());

    const days: HistoryDay[] = [];
    for (const { e, d } of sorted) {
      const key = `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
      let day = days[days.length - 1];
      if (day?.key !== key) {
        const label = d.toLocaleDateString(locale, {
          weekday: 'long',
          day: 'numeric',
          month: 'long',
          ...(d.getFullYear() === thisYear ? {} : { year: 'numeric' }),
        });
        day = { key, label, entries: [] };
        days.push(day);
      }
      const meta = [e.actor, time.format(d)].filter((p) => !!p).join(' · ');
      day.entries.push({ ...e, meta });
    }
    return days;
  });
}
