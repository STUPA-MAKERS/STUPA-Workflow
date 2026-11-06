import { ChangeDetectionStrategy, Component, computed, effect, inject, input, model, signal, untracked } from '@angular/core';
import type { Subscription } from 'rxjs';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoLink, type TodoLinkView, type TodoViewFact } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { dayMonthYear } from '@shared/date-format';
import { formatMoney } from '@shared/format-money';
import { resolveI18n } from '@shared/forms/i18n-text';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import {
  IconComponent,
  MEDIA,
  mediaQuery,
  NoteComponent,
  SectionComponent,
  SideSheetComponent,
} from '@stupa-makers/ui-kit';
import { LINK_ICON, linkSub, VOTE_RESULT_LABEL, VOTE_STATUS_LABEL } from '../todos.util';

/** The values of a fact that the sheet translates, by the key of the fact. */
const VALUE_LABEL: Record<string, Record<string, TranslationKey>> = {
  voteStatus: VOTE_STATUS_LABEL,
  voteResult: VOTE_RESULT_LABEL,
  invoiceStatus: { open: 'invoices.status.open', paid: 'invoices.status.paid' },
  bookingKind: {
    expense: 'expenses.kind.expense',
    income: 'expenses.kind.income',
    transfer: 'expenses.kind.transfer',
  },
  paymentMethod: {
    ueberweisung: 'expenses.paymentMethod.ueberweisung',
    bar: 'expenses.paymentMethod.bar',
    lastschrift: 'expenses.paymentMethod.lastschrift',
    karte: 'expenses.paymentMethod.karte',
    paypal: 'expenses.paymentMethod.paypal',
  },
  meetingStatus: {
    planned: 'meetings.status.planned',
    live: 'meetings.status.live',
    closed: 'meetings.status.closed',
  },
};

/** The heading of the list of rows, by the kind of the target. */
const ROWS_HEADING: Partial<Record<TodoLink['kind'], TranslationKey>> = {
  meeting: 'todos.linkView.agenda',
  agenda_item: 'todos.linkView.votes',
  todo: 'todos.card.checklist',
};

/**
 * The read sheet of a link (spec 000487): a person who reads a card reads what the card
 * links, also an Antrag, a Buchung or a meeting that the person cannot open otherwise.
 * The sheet shows the facts of the target read only, without the PII fields of an Antrag
 * and without the links of a linked card. A bottom sheet on a phone, a side sheet else.
 */
@Component({
  selector: 'app-todo-link-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, IconComponent, MarkdownViewComponent, NoteComponent, SectionComponent, SideSheetComponent],
  templateUrl: './todo-link-view.component.html',
  styleUrl: './todo-link-view.component.scss',
})
export class TodoLinkViewComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly t = this.i18n.translate.bind(this.i18n);

  readonly open = model(false);
  readonly cardId = input.required<Uuid>();
  readonly link = input<TodoLink | null>(null);

  readonly phone = mediaQuery(MEDIA.phone);
  readonly view = signal<TodoLinkView | null>(null);
  protected readonly failed = signal(false);

  readonly icon = computed(() => LINK_ICON[this.link()?.kind ?? 'todo']);
  readonly heading = computed(() => this.view()?.title ?? this.link()?.title ?? '');
  readonly sub = computed(() => {
    const link = this.link();
    return link ? linkSub(link, this.i18n.formatLocale(), this.i18n.uiLocale(), this.t) : '';
  });

  /** The read of the open link; a read for another link drops it. */
  private request: Subscription | null = null;

  constructor() {
    effect(() => {
      const link = this.link();
      const open = this.open();
      const cardId = this.cardId();
      untracked(() => {
        if (open && link) this.load(cardId, link.id);
      });
    });
  }

  private load(cardId: Uuid, linkId: Uuid): void {
    this.request?.unsubscribe();
    this.view.set(null);
    this.failed.set(false);
    this.request = this.api.linkView(cardId, linkId).subscribe({
      next: (view) => this.view.set(view),
      error: () => this.failed.set(true),
    });
  }

  plain(view: TodoLinkView): TodoViewFact[] {
    return view.facts.filter((f) => f.format !== 'markdown');
  }

  texts(view: TodoLinkView): TodoViewFact[] {
    return view.facts.filter((f) => f.format === 'markdown');
  }

  /** The heading of the rows: the agenda, the votes of a TOP, the checklist of a card. */
  rowsHeading(view: TodoLinkView): string {
    const key = ROWS_HEADING[view.kind];
    return key ? this.t(key) : '';
  }

  /** The label of a fact: the field label of a form answer, else `todos.linkView.<key>`. */
  label(fact: TodoViewFact): string {
    if (fact.label) return resolveI18n(fact.label, this.i18n.uiLocale());
    return this.t(`todos.linkView.${fact.key}` as TranslationKey);
  }

  value(fact: TodoViewFact): string {
    const locale = this.i18n.formatLocale();
    if (fact.format === 'money') return formatMoney(fact.value, locale);
    if (fact.format === 'date') return dayMonthYear(fact.value, locale);
    const key = VALUE_LABEL[fact.key]?.[fact.value];
    return key ? this.t(key) : fact.value;
  }

  /** "TOP 3" for a meeting, the result or status of a vote, else nothing. */
  rowMeta(index: number, meta: string | null): string {
    if (this.view()?.kind === 'meeting') return this.t('todos.link.top', { n: index + 1 });
    if (!meta) return '';
    const key = VOTE_RESULT_LABEL[meta as never] ?? VOTE_STATUS_LABEL[meta as never];
    return key ? this.t(key) : meta;
  }
}
