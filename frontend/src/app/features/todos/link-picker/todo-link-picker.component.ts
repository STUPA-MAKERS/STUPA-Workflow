import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import type { Uuid } from '@core/api/models';
import { TodosApiService, type TodoLinkKind, type TodoLinkTarget } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { liveSearch } from '@shared/live-search';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { LINK_ICON, linkSub, type Translate } from '../todos.util';

type PickerKind = TodoLinkKind | 'all';

interface PickerGroup {
  key: string;
  label: TranslationKey;
  hits: TodoLinkTarget[];
}

const KIND_CHIPS: readonly { value: PickerKind; label: TranslationKey }[] = [
  { value: 'all', label: 'todos.picker.all' },
  { value: 'application', label: 'todos.picker.applications' },
  { value: 'meeting', label: 'todos.picker.meetings' },
  { value: 'agenda_item', label: 'todos.picker.tops' },
  { value: 'ticket', label: 'todos.picker.tickets' },
  { value: 'todo', label: 'todos.picker.todos' },
];

/** The key of a link target in the `linked` set. */
export function linkKey(kind: TodoLinkKind, id: Uuid): string {
  return `${kind}:${id}`;
}

/**
 * "Verknüpfen" (frame 3): search what a card can link. The server lists per kind only
 * what the person may read. The chips narrow the kind; the hits come in groups (Anträge,
 * Sitzungen und TOPs, Tickets, To-Dos), a linked target carries a check mark. A pick of
 * a linked target takes the link off again.
 *
 * Desktop: a panel that the parent places (absolute) under its button. Phone: the
 * shared bottom sheet.
 */
@Component({
  selector: 'app-todo-link-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe, IconComponent, SideSheetComponent],
  host: { '[class.lp-host--open]': 'open() && !phone()' },
  templateUrl: './todo-link-picker.component.html',
  styleUrl: './todo-link-picker.component.scss',
})
export class TodoLinkPickerComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly open = model(false);
  /** The card itself never shows as a to-do hit. */
  readonly excludeCardId = input<Uuid | null>(null);
  /** The targets the card links now (`kind:id`). */
  readonly linked = input<ReadonlySet<string>>(new Set());
  readonly picked = output<TodoLinkTarget>();

  readonly phone = mediaQuerySignal(MEDIA.phone);
  readonly chips = KIND_CHIPS;
  readonly kind = signal<PickerKind>('all');
  readonly hits = signal<TodoLinkTarget[]>([]);
  readonly failed = signal(false);

  private readonly field = viewChild<ElementRef<HTMLInputElement>>('field');

  readonly search = liveSearch<TodoLinkTarget[]>({
    run: (q) => {
      this.failed.set(false);
      return this.api.linkTargets(q, this.kind(), this.excludeCardId());
    },
    result: (hits) => this.hits.set(hits),
    reset: () => this.hits.set([]),
    error: () => {
      this.hits.set([]);
      this.failed.set(true);
    },
  });

  readonly groups = computed<PickerGroup[]>(() => {
    const by = (kinds: TodoLinkKind[]) => this.hits().filter((h) => kinds.includes(h.kind));
    const all: PickerGroup[] = [
      { key: 'application', label: 'todos.picker.applications', hits: by(['application']) },
      { key: 'meeting', label: 'todos.picker.meetingsAndTops', hits: by(['meeting', 'agenda_item']) },
      { key: 'ticket', label: 'todos.picker.tickets', hits: by(['ticket']) },
      { key: 'todo', label: 'todos.picker.todos', hits: by(['todo']) },
    ];
    return all.filter((g) => g.hits.length);
  });

  constructor() {
    // Each opening starts empty, with the focus in the field.
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.kind.set('all');
        this.search.clear();
        this.failed.set(false);
        queueMicrotask(() => this.field()?.nativeElement.focus());
      });
    });
  }

  setKind(kind: PickerKind): void {
    if (kind === this.kind()) return;
    this.kind.set(kind);
    this.search.refresh();
  }

  icon(hit: TodoLinkTarget) {
    return LINK_ICON[hit.kind];
  }

  sub(hit: TodoLinkTarget): string {
    return linkSub(hit, this.i18n.formatLocale(), this.i18n.locale(), this.t);
  }

  isLinked(hit: TodoLinkTarget): boolean {
    return this.linked().has(linkKey(hit.kind, hit.targetId));
  }

  pick(hit: TodoLinkTarget): void {
    this.picked.emit(hit);
  }

  close(): void {
    this.open.set(false);
  }

  onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this.close();
    }
  }
}
