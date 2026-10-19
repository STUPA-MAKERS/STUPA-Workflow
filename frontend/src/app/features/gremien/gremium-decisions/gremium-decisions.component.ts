import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import type { Subscription } from 'rxjs';
import {
  GremienApiService,
  type GremiumDecision,
  type GremiumDecisionKind,
  type GremiumDecisionPage,
  type GremiumDecisionQuery,
  type GremiumDecisionResultFilter,
} from '@core/api/gremien.service';
import type { VoteResult } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { liveSearch } from '@shared/live-search';
import { voteResultStatus, type StatusView } from '@shared/status-kind.util';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { electionStatus } from '../../voting/election.util';
import { GREMIEN_NOW } from '../gremien.store';
import { monthKey, shiftMonth } from '../gremien.util';
import { dayMonth, monthYear } from '@shared/date-format';
import { StickyBarComponent } from '@shared/ui/sticky-bar/sticky-bar.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { RowChevronComponent } from '@shared/ui/row-chevron/row-chevron.component';
import { majorityLabel } from '../../meetings/meetings-display.util';
import { formatMoney } from '@shared/format-money';

export type DecisionsResult = '' | GremiumDecisionResultFilter;
export type DecisionsKind = '' | GremiumDecisionKind;
export type DecisionsSince = '' | 'last3' | 'last12';

/** One vote, ready for the template. */
export interface DecisionRow {
  readonly decision: GremiumDecision;
  readonly title: string;
  /** The parts of the sub line: kind, votes, majority. */
  readonly parts: readonly string[];
  readonly status: StatusView;
  /** The names after "Gewählt:". */
  readonly elected: string;
}

/** The votes of one meeting in one month. */
export interface DecisionGroup {
  readonly key: string;
  readonly label: string;
  /** "33. Sitzung · 06.10." or "Ohne Sitzung". */
  readonly meeting: string;
  readonly rows: DecisionRow[];
}

const KIND_KEYS: Record<GremiumDecisionKind, TranslationKey> = {
  application: 'gremien.decisions.kindApplication',
  motion: 'gremien.decisions.kindMotion',
  election: 'gremien.decisions.kindElection',
};
const NO_RESULT: StatusView = { kind: 'muted', key: 'gremien.decisions.noResult' };

/**
 * The sub-tab "Beschlüsse" of a gremium: every closed vote, the newest first, grouped by
 * month and meeting. A row shows the question, the kind (an application with its amount,
 * a motion or an election), the votes, the majority rule and the result, and opens the
 * vote in `/voting/:id`.
 *
 * The search runs on the server while the user types (`liveSearch`). The chips
 * "Ergebnis", "Art" and "Zeitraum" go to the server too, because the list comes in pages
 * ("Weitere laden"). A secret vote shows only its sums, as the vote itself does.
 */
@Component({
  selector: 'app-gremium-decisions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RowChevronComponent,
    NoteComponent,
    StickyBarComponent,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    ListItemComponent,
    SearchPillComponent,
    SkeletonComponent,
    StatusTextComponent,
  ],
  templateUrl: './gremium-decisions.component.html',
  styleUrl: './gremium-decisions.component.scss',
})
export class GremiumDecisionsComponent {
  private readonly api = inject(GremienApiService);
  private readonly i18n = inject(I18nService);
  private readonly now = inject(GREMIEN_NOW);

  readonly gremiumId = input.required<string>();

  readonly phone = mediaQuerySignal(MEDIA.phone);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly items = signal<readonly GremiumDecision[]>([]);
  readonly nextCursor = signal<string | null>(null);
  readonly loadingMore = signal(false);
  readonly moreError = signal(false);
  readonly result = signal<DecisionsResult>('');
  readonly kind = signal<DecisionsKind>('');
  readonly since = signal<DecisionsSince>('');
  private moreSub: Subscription | null = null;

  /** The search field: it searches while the user types, from the first character. */
  readonly search = liveSearch<GremiumDecisionPage>({
    minLength: 1,
    run: (q) => {
      this.moreSub?.unsubscribe();
      this.loadingMore.set(false);
      this.loading.set(true);
      this.error.set(false);
      return this.api.decisions(this.gremiumId(), this.query(q));
    },
    result: (page) => {
      this.items.set(page.items);
      this.nextCursor.set(page.nextCursor);
      this.moreError.set(false);
      this.loading.set(false);
    },
    error: () => {
      this.items.set([]);
      this.nextCursor.set(null);
      this.error.set(true);
      this.loading.set(false);
    },
  });

  readonly resultOptions = computed<FilterSelectOption[]>(() =>
    this.options([
      ['', 'gremien.decisions.resultAll'],
      ['passed', 'gremien.decisions.resultPassed'],
      ['rejected', 'gremien.decisions.resultRejected'],
    ]),
  );
  readonly kindOptions = computed<FilterSelectOption[]>(() =>
    this.options([
      ['', 'gremien.decisions.kindAll'],
      ['application', 'gremien.decisions.kindApplication'],
      ['motion', 'gremien.decisions.kindMotion'],
      ['election', 'gremien.decisions.kindElection'],
    ]),
  );
  readonly sinceOptions = computed<FilterSelectOption[]>(() =>
    this.options([
      ['', 'gremien.decisions.sinceAll'],
      ['last3', 'gremien.decisions.since3'],
      ['last12', 'gremien.decisions.since12'],
    ]),
  );
  readonly resultText = computed(() =>
    this.result() ? this.chipText('gremien.decisions.result', this.resultOptions(), this.result()) : null,
  );
  readonly kindText = computed(() =>
    this.kind() ? this.chipText('gremien.decisions.kind', this.kindOptions(), this.kind()) : null,
  );
  readonly sinceText = computed(() => this.chipText('gremien.decisions.since', this.sinceOptions(), this.since()));

  readonly filterActive = computed(
    () => this.result() !== '' || this.kind() !== '' || this.since() !== '' || this.search.applied() !== '',
  );

  readonly groups = computed<DecisionGroup[]>(() => {
    const locale = this.i18n.formatLocale();
    const out = new Map<string, DecisionGroup>();
    for (const d of this.items()) {
      const day = d.meetingDate ?? d.closedAt?.slice(0, 10) ?? null;
      const month = day ? day.slice(0, 7) : '';
      const key = `${month}|${d.meetingId ?? ''}`;
      let group = out.get(key);
      if (!group) {
        group = {
          key,
          label: month ? monthYear(month, locale) : this.i18n.translate('gremien.decisions.undated'),
          meeting: d.meetingId
            ? [d.meetingTitle, dayMonth(d.meetingDate, locale)].filter(Boolean).join(' · ')
            : this.i18n.translate('gremien.decisions.noMeeting'),
          rows: [],
        };
        out.set(key, group);
      }
      group.rows.push(this.toRow(d));
    }
    return [...out.values()];
  });

  constructor() {
    effect(() => {
      this.gremiumId();
      this.result();
      this.kind();
      this.since();
      untracked(() => this.search.refresh());
    });
  }

  /** Read the first page again (after an error). */
  load(): void {
    this.search.refresh();
  }

  setResult(value: string): void {
    this.result.set(value as DecisionsResult);
  }

  setKind(value: string): void {
    this.kind.set(value as DecisionsKind);
  }

  setSince(value: string): void {
    this.since.set(value as DecisionsSince);
  }

  /** "Weitere laden": the next page, behind the rows on screen. */
  loadMore(): void {
    const cursor = this.nextCursor();
    if (!cursor || this.loadingMore()) return;
    this.loadingMore.set(true);
    this.moreError.set(false);
    this.moreSub = this.api
      .decisions(this.gremiumId(), { ...this.query(this.search.applied()), cursor })
      .subscribe({
        next: (page) => {
          this.items.set([...this.items(), ...page.items]);
          this.nextCursor.set(page.nextCursor);
          this.loadingMore.set(false);
        },
        error: () => {
          this.moreError.set(true);
          this.loadingMore.set(false);
        },
      });
  }

  private query(q: string): GremiumDecisionQuery {
    const since = this.since();
    const months = since === 'last3' ? -2 : since === 'last12' ? -11 : null;
    return {
      q: q || null,
      result: this.result() || null,
      kind: this.kind() || null,
      since: months === null ? null : `${shiftMonth(monthKey(this.now()), months)}-01`,
    };
  }

  private options(pairs: readonly (readonly [string, TranslationKey])[]): FilterSelectOption[] {
    return pairs.map(([value, key]) => ({ value, label: this.i18n.translate(key) }));
  }

  private chipText(labelKey: TranslationKey, options: FilterSelectOption[], value: string): string {
    const label = options.find((o) => o.value === value)?.label ?? '';
    return `${this.i18n.translate(labelKey)}: ${label}`;
  }

  private toRow(d: GremiumDecision): DecisionRow {
    const t = (key: TranslationKey, params?: Record<string, string | number>) => this.i18n.translate(key, params);
    const parts: string[] = [];
    if (d.kind === 'application') {
      const amount = formatMoney(d.amount, this.i18n.formatLocale());
      parts.push(amount ? `${t(KIND_KEYS.application)} · ${amount}` : t(KIND_KEYS.application));
    } else {
      parts.push(t(KIND_KEYS[d.kind]));
    }
    if (d.secret) parts.push(t('gremien.decisions.secret'));
    if (d.counts) {
      parts.push(
        t('gremien.decisions.counts', { yes: d.counts.yes, no: d.counts.no, abstain: d.counts.abstain }),
      );
    } else {
      parts.push(d.ballots === 1 ? t('gremien.decisions.ballots1') : t('gremien.decisions.ballots', { n: d.ballots }));
    }
    if (d.majorityRule) parts.push(majorityLabel(d.majorityRule, false, t));
    let status = NO_RESULT;
    if (d.result) {
      status = d.kind === 'election' ? electionStatus(d.result) : voteResultStatus(d.result as VoteResult);
    }
    return {
      decision: d,
      title: d.question || d.applicationTitle || t('gremien.decisions.untitled'),
      parts,
      status,
      elected: d.result === 'elected' ? d.elected.join(', ') : '',
    };
  }
}
