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
import { RouterLink } from '@angular/router';
import type { Subscription } from 'rxjs';
import {
  GremienApiService,
  type GremiumMeeting,
} from '@core/api/gremien.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { meetingStatus, type StatusView } from '@shared/status-kind.util';
import { DateBlockComponent } from '@shared/ui/date-block/date-block.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { IconComponent, MEDIA, mediaQuery } from '@stupa-makers/ui-kit';
import { topsLabel } from '../../meetings/meetings-overview.util';
import { GREMIEN_NOW } from '../gremien.store';
import { monthKey, shiftMonth } from '../gremien.util';
import { isoDay, monthYear, shortTime, weekdayDate } from '@shared/date-format';
import { NoteComponent } from '@shared/ui/note/note.component';
import { RowChevronComponent } from '@shared/ui/row-chevron/row-chevron.component';

export type MeetingsRange = '' | 'upcoming' | 'past6' | 'past12';
export type MeetingsProtocol = '' | 'final' | 'draft' | 'none';

export interface MeetingRow {
  readonly meeting: GremiumMeeting;
  readonly sub: string;
  readonly status: StatusView;
  /** "x/y" for a closed meeting. */
  readonly attendance: string | null;
  readonly attendanceLabel: string | null;
}

export interface MeetingGroup {
  readonly key: string;
  readonly label: string;
  readonly upcoming: boolean;
  readonly rows: MeetingRow[];
}

const PROTOCOL_STATUS: Record<string, StatusView> = {
  final: { kind: 'accent', key: 'gremien.meetings.protocolFinal' },
  draft: { kind: 'warn', key: 'gremien.meetings.protocolDraft' },
  rendering: { kind: 'neutral', key: 'gremien.meetings.protocolRendering' },
};
const NO_PROTOCOL: StatusView = { kind: 'muted', key: 'gremien.meetings.protocolMissing' };

/**
 * The sub-tab "Sitzungen" of a gremium: the coming meetings first, then the closed ones
 * by month, the newest first. A row shows the date, the title, the time, the agenda
 * items, the protocol state and "x/y anwesend", and opens the meeting in `/meetings/:id`.
 * The chips "Zeitraum" and "Protokoll" filter in the browser.
 */
@Component({
  selector: 'app-gremium-meetings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RowChevronComponent,
    NoteComponent,
    RouterLink,
    TranslatePipe,
    IconComponent,
    DateBlockComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    ListItemComponent,
    SkeletonComponent,
    StatusTextComponent,
  ],
  templateUrl: './gremium-meetings.component.html',
  styleUrl: './gremium-meetings.component.scss',
})
export class GremiumMeetingsComponent {
  private readonly api = inject(GremienApiService);
  private readonly i18n = inject(I18nService);
  private readonly now = inject(GREMIEN_NOW);

  readonly gremiumId = input.required<string>();
  /** The number of meetings, for the tab bar. */
  readonly count = output<number>();

  readonly phone = mediaQuery(MEDIA.phone);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly items = signal<readonly GremiumMeeting[]>([]);
  readonly range = signal<MeetingsRange>('');
  readonly protocol = signal<MeetingsProtocol>('');
  private sub: Subscription | null = null;

  readonly rangeOptions = computed<FilterSelectOption[]>(() =>
    (
      [
        ['', 'gremien.meetings.rangeAll'],
        ['upcoming', 'gremien.meetings.rangeUpcoming'],
        ['past6', 'gremien.meetings.range6'],
        ['past12', 'gremien.meetings.range12'],
      ] as const
    ).map(([value, key]) => ({ value, label: this.i18n.translate(key) })),
  );
  readonly protocolOptions = computed<FilterSelectOption[]>(() =>
    (
      [
        ['', 'gremien.meetings.protocolAll'],
        ['final', 'gremien.meetings.protocolFinal'],
        ['draft', 'gremien.meetings.protocolDraft'],
        ['none', 'gremien.meetings.protocolMissing'],
      ] as const
    ).map(([value, key]) => ({ value, label: this.i18n.translate(key) })),
  );
  readonly rangeText = computed(() => this.chipText('gremien.meetings.range', this.rangeOptions(), this.range()));
  readonly protocolText = computed(() =>
    this.protocol() ? this.chipText('gremien.meetings.protocol', this.protocolOptions(), this.protocol()) : null,
  );

  private readonly filtered = computed(() => {
    const range = this.range();
    const protocol = this.protocol();
    const today = isoDay(this.now());
    const since =
      range === 'past6' || range === 'past12'
        ? `${shiftMonth(monthKey(this.now()), range === 'past6' ? -5 : -11)}-01`
        : null;
    return this.items().filter((m) => {
      const upcoming = m.status !== 'closed';
      if (range === 'upcoming' && !upcoming) return false;
      if (since && (upcoming || !m.date || m.date < since || m.date > today)) return false;
      if (protocol === 'none' && m.protocolStatus) return false;
      if (protocol === 'final' && m.protocolStatus !== 'final') return false;
      if (protocol === 'draft' && m.protocolStatus !== 'draft' && m.protocolStatus !== 'rendering') {
        return false;
      }
      return true;
    });
  });

  readonly groups = computed<MeetingGroup[]>(() => {
    const locale = this.i18n.formatLocale();
    const rows = this.filtered();
    const coming = rows
      .filter((m) => m.status !== 'closed')
      .sort((a, b) => (a.date ?? '9999').localeCompare(b.date ?? '9999') || (a.startTime ?? '').localeCompare(b.startTime ?? ''));
    const out: MeetingGroup[] = [];
    if (coming.length) {
      out.push({
        key: 'upcoming',
        label: this.i18n.translate('gremien.meetings.upcoming'),
        upcoming: true,
        rows: coming.map((m) => this.toRow(m)),
      });
    }
    const past = rows
      .filter((m) => m.status === 'closed')
      .sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''));
    for (const m of past) {
      const key = m.date ? m.date.slice(0, 7) : 'undated';
      let group = out.find((g) => g.key === key);
      if (!group) {
        group = {
          key,
          label: m.date ? monthYear(key, locale) : this.i18n.translate('gremien.meetings.undated'),
          upcoming: false,
          rows: [],
        };
        out.push(group);
      }
      group.rows.push(this.toRow(m));
    }
    return out;
  });

  readonly filterActive = computed(() => this.range() !== '' || this.protocol() !== '');

  constructor() {
    effect(() => {
      const id = this.gremiumId();
      untracked(() => this.load(id));
    });
  }

  load(id = this.gremiumId()): void {
    this.sub?.unsubscribe();
    this.loading.set(true);
    this.error.set(false);
    this.sub = this.api.meetings(id).subscribe({
      next: (rows) => {
        this.items.set(rows);
        this.loading.set(false);
        this.count.emit(rows.length);
      },
      error: () => {
        this.items.set([]);
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  setRange(value: string): void {
    this.range.set(value as MeetingsRange);
  }

  setProtocol(value: string): void {
    this.protocol.set(value as MeetingsProtocol);
  }

  private chipText(labelKey: TranslationKey, options: FilterSelectOption[], value: string): string {
    const label = options.find((o) => o.value === value)?.label ?? '';
    return `${this.i18n.translate(labelKey)}: ${label}`;
  }

  private toRow(m: GremiumMeeting): MeetingRow {
    const locale = this.i18n.formatLocale();
    const closed = m.status === 'closed';
    const status = closed ? (PROTOCOL_STATUS[m.protocolStatus ?? ''] ?? NO_PROTOCOL) : meetingStatus(m.status);
    const parts: string[] = [];
    if (this.phone()) {
      if (m.date) parts.push(weekdayDate(m.date, locale, { year: false }));
    } else {
      const date = weekdayDate(m.date, locale);
      if (date) parts.push(date);
      const time = [shortTime(m.startTime), shortTime(m.endTime)].filter(Boolean).join('–');
      if (time) parts.push(time);
      parts.push(topsLabel(m.agendaItemCount, (k, p) => this.i18n.translate(k, p)));
    }
    return {
      meeting: m,
      sub: parts.join(' · '),
      status,
      attendance: closed ? `${m.presentCount}/${m.memberCount}` : null,
      attendanceLabel: closed
        ? this.i18n.translate('gremien.meetings.presentOf', { present: m.presentCount, total: m.memberCount })
        : null,
    };
  }
}
