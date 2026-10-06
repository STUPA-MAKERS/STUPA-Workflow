import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { StatusKind } from '../../status-kind.util';
import { StatusTextComponent } from '../status-text/status-text.component';

/** One changed field of an event, for example of a new version. */
export interface HistoryChange {
  /** The colour of the tag: `warn` for a change, `accent` for an addition, `error` for a
   *  removal. */
  kind: StatusKind;
  /** "Geändert", "Hinzugefügt", "Entfernt". */
  tag: string;
  /** The name of the field. */
  label: string;
  /** The value before, struck through. Leave it out for a field without a short text. */
  old?: string | null;
  /** The value after. */
  new?: string | null;
  /**
   * The long values of the change (a text, the cost positions, a table), one block each.
   * The line then has a button that opens them below it ("Werte anzeigen"). A block
   * keeps its line breaks. Leave out a side that does not exist, for example `old` for
   * an added field.
   */
  detail?: { old?: string | null; new?: string | null } | null;
}

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
  /** One more line, for example the transition ("Übergang „Prüfung beginnen“"). A line
   *  break in the text starts a new line. */
  body?: string | null;
  /** The changed fields, one line each, below the body. */
  changes?: readonly HistoryChange[] | null;
  /** A link below the body, for example to the vote that decided the status. */
  link?: { label: string; route: readonly string[] } | null;
}

interface HistoryDay {
  /** `y-m-d`, or `none` for the entries without a valid date. */
  key: string;
  label: string;
  entries: (HistoryEntry & { meta: string })[];
}

let nextId = 0;

/**
 * A history, grouped by day: newest day first, and in each day the newest event first.
 *
 * A status title takes its colour (`kind`); any other event stays in the text colour.
 * The changed fields of an event follow as lines: "Geändert Feld: alt → neu". A change
 * with long values (`detail`) gets a button that opens the old and the new value as
 * blocks below the line, so a changed text stays readable in full. The meta line gives
 * the actor and the time. Each day is a list, named by its date.
 * Entries with a missing or invalid `at` go into a last group, "Ohne Datum", without a
 * time.
 */
@Component({
  selector: 'app-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, RouterLink, StatusTextComponent, TranslatePipe],
  templateUrl: './history.component.html',
  styleUrl: './history.component.scss',
})
export class HistoryComponent {
  private readonly i18n = inject(I18nService);

  readonly entries = input.required<readonly HistoryEntry[]>();
  /** The surface of the rows; see `app-field-group`. */
  readonly surface = input<1 | 2 | 3>(2);

  protected readonly id = `history-${nextId++}`;

  /** The changes whose long values the reader opened, as `day:entry:change`. */
  private readonly opened = signal<ReadonlySet<string>>(new Set());

  /** The values of this change are open. */
  protected isOpen(key: string): boolean {
    return this.opened().has(key);
  }

  /** Open or close the values of a change. */
  protected toggle(key: string): void {
    this.opened.update((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  /**
   * The lines of a long value. The leading spaces of a line become its indent, so a
   * wrapped line stays in its column (the offers below a cost position). A tab counts as
   * four spaces.
   */
  protected lines(text: string | null | undefined): { text: string; indent: number }[] {
    return (text ?? '').split('\n').map((line) => {
      const lead = /^[ \t]*/.exec(line)?.[0] ?? '';
      return {
        text: line.slice(lead.length),
        indent: [...lead].reduce((n, ch) => n + (ch === '\t' ? 4 : 1), 0),
      };
    });
  }

  /** A change value is given: an empty text counts, `null` and `undefined` do not. */
  protected has(value: string | null | undefined): boolean {
    return value !== null && value !== undefined;
  }

  protected readonly days = computed<HistoryDay[]>(() => {
    const locale = this.i18n.formatLocale();
    const thisYear = new Date().getFullYear();
    const time = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' });
    const dated: { e: HistoryEntry; d: Date }[] = [];
    const undated: HistoryEntry[] = [];
    for (const e of this.entries()) {
      // `new Date(null)` is 1970, so a missing value counts as invalid before the parse.
      const d = e.at ? new Date(e.at) : new Date(NaN);
      if (Number.isNaN(d.getTime())) undated.push(e);
      else dated.push({ e, d });
    }
    const sorted = dated.sort((a, b) => b.d.getTime() - a.d.getTime());

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
    if (undated.length > 0) {
      days.push({
        key: 'none',
        label: this.i18n.translate('ui.history.noDate'),
        entries: undated.map((e) => ({ ...e, meta: e.actor ?? '' })),
      });
    }
    return days;
  });
}
