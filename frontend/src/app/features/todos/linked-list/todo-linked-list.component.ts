import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { catchError, map, of, switchMap } from 'rxjs';
import { NgTemplateOutlet } from '@angular/common';
import { RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import {
  TodosApiService,
  type LinkRow,
  type LinksOut,
  type TodoLinkKind,
  type TodoLinkTarget,
  type TodoLinkedCard,
} from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate } from '@core/i18n/translations';
import { dayMonth } from '@shared/date-format';
import { formatMoney, moneyNumber } from '@shared/format-money';
import { LINK_ICON, LINK_KIND_LABEL, eventDays, linkSub, linkTitle, splitUrl } from '../todos.util';
import {
  type AvatarSize,
  AvatarStackComponent,
  ButtonComponent,
  EmptyStateComponent,
  IconComponent,
  type IconName,
  SectionComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { TodoLinkPickerComponent, linkKey } from '../link-picker/todo-link-picker.component';
import { type NewTodoLink, TodoNewDialogComponent } from '../new-dialog/todo-new-dialog.component';
import { FeatureService } from '@core/features/feature.service';
import { TodoLinkedRefresh, linkedKey } from './todo-linked-refresh';
import { personName } from '@shared/person-label.util';

/** A row above the cards in the same look, for the object that the list belongs to. */
export interface LinkedLead {
  readonly icon: IconName;
  readonly title: string;
  readonly sub: string;
  /** The router link. The row opens it in a new tab. */
  readonly link: readonly unknown[];
  /** The query parameters of the link. */
  readonly queryParams?: Readonly<Record<string, string>>;
}

/** A linked card shown without its link row (a page passes `items`). */
const cardRow = (card: TodoLinkedCard): LinkRow => ({
  id: card.id,
  kind: 'todo',
  targetId: card.id,
  accessible: true,
  title: card.title,
  url: null,
  detail: null,
  card,
  removable: false,
  createdAt: '',
});

/**
 * The section "Verknüpft" of an element (spec 001407): every link of the element that
 * the viewer reads (`GET /links`), of any kind. A linked Event comes first, then the
 * other links in the order of the kinds, the newest first in each kind. A card shows its
 * board, its column, the due date and the people and opens on its board; any other
 * element opens its page, or shows "<Kind> (kein Zugriff)".
 *
 * Nothing linked, or the read fails: the component shows nothing, or only the `lead` row.
 * The TOP sheet puts the application of an application item there, "Antrag · Entwurf ·
 * 1.250,00 €", above the links of the TOP.
 *
 * `rows` adds linked objects that are no links: the Antrag page puts its Vorgänger and its
 * Folgeanträge there.
 *
 * A page that needs the cards itself (the ticket page counts the open ones) passes them
 * as `items`; the list then reads nothing and shows only those cards.
 *
 * `actions` adds the icon buttons "Verknüpfen" (one picker over every kind, spec 001408)
 * and "To-Do anlegen" to the head, also without a link. "Verknüpfen" shows for a person
 * who may change the element or writes a board, "To-Do anlegen" for a person who writes a
 * board. The new card links the element and starts on the board of `gremiumId`. A page
 * with its own head for them (the To-Dos sheet of a meeting, `headActions`) opens the two
 * through `newOpen` and `linkOpen`. A row that the person may take off has an ×
 * (spec 001404). `emptyHeading` shows an empty state when nothing is linked.
 */
@Component({
  selector: 'app-todo-linked-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    SectionComponent,
    RouterLink,
    TranslatePipe,
    AvatarStackComponent,
    ButtonComponent,
    EmptyStateComponent,
    IconComponent,
    TodoLinkPickerComponent,
    TodoNewDialogComponent,
  ],
  templateUrl: './todo-linked-list.component.html',
  styleUrl: './todo-linked-list.component.scss',
})
export class TodoLinkedListComponent {
  private readonly api = inject(TodosApiService);
  private readonly refresh = inject(TodoLinkedRefresh);
  private readonly features = inject(FeatureService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly kind = input.required<TodoLinkKind>();
  readonly targetId = input.required<Uuid>();
  /** The id of the heading, unique on the page. */
  readonly headingId = input('todo-linked');

  /**
   * Show the "Verknüpft" heading. The TOP sheet leaves it out, because there the list
   * stands under the TOP title; the section keeps the name for the screen reader.
   */
  readonly showTitle = input(true);
  /** The cards to show, read by the page. `null` reads the links here. */
  readonly items = input<readonly TodoLinkedCard[] | null>(null);
  readonly avatarSize = input<AvatarSize>('sm');
  /** The row above the links. */
  readonly lead = input<LinkedLead | null>(null);
  /**
   * More objects of the same kind linked to the object, such as the Vorgänger and the
   * Folgeanträge of an Antrag. They stand above the links and open in the same tab.
   */
  readonly rows = input<readonly LinkedLead[]>([]);
  /** The head holds "Verknüpfen" and "To-Do anlegen". */
  readonly actions = input(false);
  /**
   * The page shows the two actions in a head of its own (the To-Dos sheet of a meeting)
   * and opens them through `newOpen` and `linkOpen`; `canAct` tells it when.
   */
  readonly headActions = input(false);
  /** The new card starts on the board of this Gremium, when the person writes it. */
  readonly gremiumId = input<Uuid | null>(null);
  /** The text of the element in the link chip of the new card. */
  readonly linkLabel = input('');
  /** Shown when nothing links the element; empty: the list shows nothing then. */
  readonly emptyHeading = input('');
  readonly size = input<'md' | 'lg'>('md');

  readonly newOpen = signal(false);
  readonly linkOpen = signal(false);

  /** The person writes a board, so "To-Do anlegen" can do something (spec 000547). */
  readonly canAct = toSignal(
    toObservable(computed(() => this.actions() || this.headActions())).pipe(
      switchMap((on) =>
        on && this.features.isOn('todos')
          ? this.api.boards().pipe(
              map((boards) => boards.some((b) => b.canWrite)),
              catchError(() => of(false)),
            )
          : of(false),
      ),
    ),
    { initialValue: false },
  );
  /** While `Boards` is off the section keeps its other links and has no "To-Do anlegen". */
  readonly showNew = computed(() => this.actions() && this.canAct() && this.features.isOn('todos'));
  /** "Verknüpfen": the person changes the element, or a card that may link it (spec 001404). */
  readonly showLink = computed(() => this.actions() && (this.canLink() || this.showNew()));
  readonly showActions = computed(() => this.showNew() || this.showLink());
  readonly newLinks = computed<NewTodoLink[]>(() => [
    {
      kind: this.kind(),
      targetId: this.targetId(),
      label: [this.t(LINK_KIND_LABEL[this.kind()]), this.linkLabel()].filter(Boolean).join(' · '),
    },
  ]);
  readonly self = computed(() => ({ kind: this.kind(), id: this.targetId() }));
  /** The ends that the element links now (`kind:id`), for the check marks of the picker. */
  readonly linkedKeys = computed(() => new Set(this.links().map((l) => linkKey(l.kind, l.targetId))));
  readonly hasRows = computed(() => !!(this.links().length || this.lead() || this.rows().length));

  private readonly loaded = signal<LinksOut | null>(null);
  readonly canLink = computed(() => this.loaded()?.canLink ?? false);
  /** The rows of the list: the read links, or the cards that the page passed. */
  readonly links = computed<readonly LinkRow[]>(() => {
    const items = this.items();
    return items ? items.map(cardRow) : (this.loaded()?.links ?? []);
  });
  private seq = 0;

  constructor() {
    effect(() => {
      const kind = this.kind();
      const id = this.targetId();
      if (this.items() !== null) return;
      untracked(() => this.load(kind, id, false));
    });
    const seen = this.refresh.last();
    effect(() => {
      const change = this.refresh.last();
      if (!change || change === seen) return;
      untracked(() => {
        if (this.items() !== null) return;
        if (change.keys.has(linkedKey(this.kind(), this.targetId()))) this.load(this.kind(), this.targetId(), true);
      });
    });
  }

  /** A new card links the element: read the list again. */
  created(): void {
    this.refresh.touch([{ kind: this.kind(), targetId: this.targetId() }]);
  }

  private load(kind: TodoLinkKind, id: Uuid, keep: boolean): void {
    const seq = ++this.seq;
    if (!keep) this.loaded.set(null);
    this.api.links(kind, id).subscribe({
      next: (out) => {
        if (seq === this.seq) this.loaded.set(out);
      },
      error: () => undefined,
    });
  }

  /**
   * A pick in the picker links the element to the hit, or takes a linked hit off again.
   * Both ends read the list again.
   */
  pick(hit: TodoLinkTarget): void {
    const row = this.links().find((l) => l.kind === hit.kind && l.targetId === hit.targetId);
    if (row) {
      this.remove(row);
      return;
    }
    this.api.link(this.self(), { kind: hit.kind, id: hit.targetId }).subscribe({
      next: (out) => {
        this.seq++;
        this.loaded.set(out);
        this.touch(hit.kind, hit.targetId);
      },
      error: () => this.toast.error(this.t('links.error.add')),
    });
  }

  remove(row: LinkRow): void {
    this.api.unlink(row.id).subscribe({
      next: () => {
        this.seq++;
        this.loaded.update((out) => out && { ...out, links: out.links.filter((l) => l.id !== row.id) });
        this.touch(row.kind, row.targetId);
      },
      error: () => this.toast.error(this.t('links.error.remove')),
    });
  }

  /** Tell the other end on screen that its links changed. */
  private touch(kind: TodoLinkKind, id: Uuid): void {
    this.refresh.touch([{ kind, targetId: id }]);
  }

  icon(row: LinkRow): IconName {
    return LINK_ICON[row.kind];
  }

  title(row: LinkRow): string {
    return linkTitle(row, this.t);
  }

  linkSub(row: LinkRow): string {
    return linkSub(row, this.i18n.formatLocale(), this.i18n.uiLocale(), this.t);
  }

  route(url: string) {
    return splitUrl(url);
  }

  /** "Veranstaltung · 20.11.–21.11.2026 · AStA": the server puts a linked Event first. */
  eventSub(card: TodoLinkedCard): string {
    const days = eventDays(card.event?.startsOn ?? null, card.event?.endsOn ?? null, this.i18n.formatLocale());
    return days
      ? this.t('todos.eventCard.linkedSub', { dates: days, board: card.boardName })
      : this.t('todos.eventCard.linkedSubNoDate', { board: card.boardName });
  }

  /** The balance of an Event with its sign. */
  money(value: string | null): string {
    return formatMoney(value, this.i18n.formatLocale(), { signed: true });
  }

  negative(value: string | null): boolean {
    return (moneyNumber(value) ?? 0) < 0;
  }

  sub(card: TodoLinkedCard): string {
    const due = card.dueDate
      ? [this.t('todos.linked.due', { date: dayMonth(card.dueDate, this.i18n.formatLocale()) })]
      : [];
    return [card.boardName, card.columnName, ...due].join(' · ');
  }

  names(card: TodoLinkedCard): string[] {
    return card.assignees.map((a) => personName(a, this.t));
  }

  ids(card: TodoLinkedCard): (string | null)[] {
    return card.assignees.map((a) => a.principalId);
  }
}
