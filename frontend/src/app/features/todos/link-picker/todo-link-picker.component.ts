import { NgTemplateOutlet } from '@angular/common';
import { DomPortalOutlet, TemplatePortal } from '@angular/cdk/portal';
import {
  ApplicationRef,
  ChangeDetectionStrategy,
  Component,
  DOCUMENT,
  DestroyRef,
  Injector,
  type TemplateRef,
  ViewContainerRef,
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
 * Desktop: a panel that floats over the whole page, like the search palette, with a
 * scrim; a click on the scrim, Escape or the × closes it, and the focus goes back to
 * where it was. The panel is rendered at the end of `<body>`, because a dialog or a
 * drawer around the picker clips and transforms its content. Phone: the shared bottom
 * sheet.
 */
@Component({
  selector: 'app-todo-link-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe, IconComponent, SideSheetComponent],
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

  private readonly document = inject(DOCUMENT);
  private readonly appRef = inject(ApplicationRef);
  private readonly injector = inject(Injector);
  private readonly viewContainer = inject(ViewContainerRef);
  private readonly pop = viewChild.required<TemplateRef<unknown>>('pop');
  private outlet: DomPortalOutlet | null = null;
  private host: HTMLElement | null = null;
  /** Where the focus was before the panel opened; it goes back there on close. */
  private returnFocus: HTMLElement | null = null;

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
        if (!this.phone()) this.returnFocus = this.document.activeElement as HTMLElement | null;
        queueMicrotask(() => this.panelRoot().querySelector<HTMLInputElement>('.lp__field')?.focus());
      });
    });
    // Desktop: the panel lives at the end of <body> while it is open.
    effect(() => {
      const floating = this.open() && !this.phone();
      untracked(() => (floating ? this.attach() : this.detach()));
    });
    inject(DestroyRef).onDestroy(() => this.detach(false));
  }

  /** The root of the open view: the sheet on a phone, the floating panel on a desktop. */
  private panelRoot(): ParentNode {
    return this.host ?? (this.viewContainer.element.nativeElement as HTMLElement);
  }

  private attach(): void {
    this.host = this.document.createElement('div');
    this.host.className = 'lp-layer';
    this.document.body.appendChild(this.host);
    this.outlet = new DomPortalOutlet(this.host, this.appRef, this.injector);
    this.outlet.attach(new TemplatePortal(this.pop(), this.viewContainer));
  }

  private detach(restoreFocus = true): void {
    if (!this.outlet) return;
    this.outlet.dispose();
    this.outlet = null;
    this.host?.remove();
    this.host = null;
    const target = this.returnFocus;
    this.returnFocus = null;
    if (restoreFocus && target?.isConnected) target.focus?.();
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

  /**
   * Escape closes the panel and Tab stays in it. Both stop here, so a dialog under the
   * panel neither closes nor pulls the focus back into itself.
   */
  onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this.close();
      return;
    }
    if (event.key !== 'Tab') return;
    event.stopPropagation();
    const panel = event.currentTarget as HTMLElement;
    const focusables = [...panel.querySelectorAll<HTMLElement>('input, button:not([disabled])')];
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = this.document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }
}
