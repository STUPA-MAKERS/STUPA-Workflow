import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  IconComponent,
  type IconName,
  type StatusKind,
  StatusTextComponent,
} from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { clock } from '@shared/date-format';
import { toggled } from '@shared/util/immutable';

/** One changed field of an event, for example of a new version. */
export interface HistoryChange {
  /** The colour of the tag: `warn` for a change, `accent` for an addition, `error` for a
   *  removal. */
  readonly kind: StatusKind;
  /** "Geändert", "Hinzugefügt", "Entfernt". */
  readonly tag: string;
  /** The name of the field. */
  readonly label: string;
  /** The value before, struck through. Leave it out for a field without a short text. */
  readonly old?: string | null;
  /** The value after. */
  readonly new?: string | null;
  /**
   * The long values of the change (a text, the cost positions, a table), one block each.
   * The line then has a button that opens them below it ("Werte anzeigen"). A block
   * keeps its line breaks. Leave out a side that does not exist, for example `old` for
   * an added field.
   */
  readonly detail?: { readonly old?: string | null; readonly new?: string | null } | null;
}

/** One event of a history. */
export interface HistoryEntry {
  /** When it happened (ISO 8601). */
  readonly at: string;
  readonly icon: IconName;
  /** What happened: the new status, or the event ("Version 2 gespeichert"). */
  readonly title: string;
  /** The colour of a status title. Leave it out for an event that is not a status. */
  readonly kind?: StatusKind | null;
  /** Who did it: a person, or the gremium for the applicant. */
  readonly actor?: string | null;
  /** One more line, for example the transition ("Übergang „Prüfung beginnen“"). A line
   *  break in the text starts a new line. */
  readonly body?: string | null;
  /** The changed fields, one line each, below the body. */
  readonly changes?: readonly HistoryChange[] | null;
  /** A link below the body, for example to the vote that decided the status. */
  readonly link?: { readonly label: string; readonly route: readonly string[] } | null;
}

interface HistoryDay {
  /** `y-m-d`, or `none` for the entries without a valid date. */
  readonly key: string;
  readonly label: string;
  readonly entries: readonly (HistoryEntry & { readonly meta: string })[];
}

/** The meta line of a dated event: the actor, then the time. */
function entryMeta(actor: string | null | undefined, time: string): string {
  return [actor, time].filter((p) => !!p).join(' · ');
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
 *
 * The disclosure button points at the values only while open, because the values are not in the DOM
 * while closed.
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
    this.opened.update((cur) => toggled(cur, key));
  }

  /**
   * The lines of a long value. The leading spaces of a line become its indent, so a
   * wrapped line stays in its column (the offers below a cost position). A tab counts as
   * four spaces.
   */
  protected lines(
    text: string | null | undefined,
  ): readonly { readonly text: string; readonly indent: number }[] {
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

  /** `new Date(null)` is 1970, so a missing value counts as invalid before the parse. */
  protected readonly days = computed<readonly HistoryDay[]>(() => {
    const locale = this.i18n.formatLocale();
    const thisYear = new Date().getFullYear();
    const parsed = this.entries().map((e) => ({ e, d: e.at ? new Date(e.at) : new Date(NaN) }));
    const undated = parsed.filter(({ d }) => Number.isNaN(d.getTime())).map(({ e }) => e);
    const sorted = parsed
      .filter(({ d }) => !Number.isNaN(d.getTime()))
      .sort((a, b) => b.d.getTime() - a.d.getTime());
    const keyOf = (d: Date): string => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
    const dayLabel = (d: Date): string =>
      d.toLocaleDateString(locale, {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        ...(d.getFullYear() === thisYear ? {} : { year: 'numeric' }),
      });
    const days = [...new Set(sorted.map(({ d }) => keyOf(d)))].map((key): HistoryDay => {
      const group = sorted.filter(({ d }) => keyOf(d) === key);
      return {
        key,
        label: dayLabel(group[0].d),
        entries: group.map(({ e, d }) => ({ ...e, meta: entryMeta(e.actor, clock(d, locale)) })),
      };
    });
    const none: HistoryDay = {
      key: 'none',
      label: this.i18n.translate('ui.history.noDate'),
      entries: undated.map((e) => ({ ...e, meta: e.actor ?? '' })),
    };
    return undated.length > 0 ? [...days, none] : days;
  });
}
