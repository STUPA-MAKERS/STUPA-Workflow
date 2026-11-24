import { FeatureService, type FeatureKey } from '@core/features/feature.service';
import { AuthService } from '@core/auth/auth.service';
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
import { PaperlessService } from '@core/api/paperless.service';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { first, switchMap } from 'rxjs';
import {
  TodosApiService,
  type LinkEnd,
  type LinkSearch,
  type TodoLinkKind,
  type TodoLinkTarget,
} from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import {
  reducedMotion,
  EmptyStateComponent,
  focusableIn,
  IconComponent,
  isApplePlatform,
  liveSearch,
  MEDIA,
  mediaQuery,
  trapTab,
} from '@stupa-makers/ui-kit';
import { LINK_ICON, linkSub } from '../todos.util';

type PickerKind = TodoLinkKind | 'all';

interface PickerGroup {
  readonly key: string;
  readonly label: TranslationKey;
  readonly hits: readonly TodoLinkTarget[];
  /** A note under the hits: Paperless does not answer (002766). */
  readonly note?: TranslationKey;
}

const KIND_CHIPS: readonly { readonly value: PickerKind; readonly label: TranslationKey }[] = [
  { value: 'all', label: 'todos.picker.all' },
  { value: 'application', label: 'todos.picker.applications' },
  { value: 'meeting', label: 'todos.picker.meetings' },
  { value: 'agenda_item', label: 'todos.picker.tops' },
  { value: 'vote', label: 'todos.picker.votes' },
  { value: 'appointment', label: 'todos.picker.appointments' },
  { value: 'gremium', label: 'todos.picker.gremien' },
  { value: 'invoice', label: 'todos.picker.invoices' },
  { value: 'expense', label: 'todos.picker.expenses' },
  { value: 'order', label: 'todos.picker.orders' },
  { value: 'budget', label: 'todos.picker.budgets' },
  { value: 'ticket', label: 'todos.picker.tickets' },
  { value: 'todo', label: 'todos.picker.todos' },
  { value: 'paperless', label: 'todos.picker.paperless' },
];

/** The rights of which one links a cost centre (spec 001410). */
const BUDGET_WRITE = ['budget.book', 'budget.structure'] as const;

/** The feature of a link kind; a kind without an entry has no switch. */
const LINK_FEATURE: Partial<Record<TodoLinkKind, FeatureKey>> = {
  meeting: 'meetings',
  agenda_item: 'meetings',
  vote: 'voting',
  appointment: 'calendar',
  invoice: 'invoices',
  expense: 'budget',
  order: 'budget',
  budget: 'budget',
  ticket: 'tickets',
  paperless: 'paperless',
};

/** The key of a link target in the `linked` set. */
export function linkKey(kind: TodoLinkKind, id: Uuid): string {
  return `${kind}:${id}`;
}

/**
 * "Verknüpfen" (spec 001408): search what an element can link. The server lists per kind only
 * what the person may read. The chips narrow the kind; the hits come in groups (Anträge,
 * Sitzungen und TOPs, Abstimmungen, Gremien, Rechnungen, Buchungen, Kostenstellen, Tickets, To-Dos), a
 * linked target carries a check mark. A pick of a linked target takes the link off again.
 *
 * A panel that floats over the whole page and looks like the global search (spec 001977),
 * on a phone too, with a scrim; a click on the scrim, Escape or the close button ("Esc",
 * on a phone ×) closes it, and the focus goes back to where it was. The panel is rendered
 * at the end of `<body>`, because a dialog or a drawer around the picker clips and
 * transforms its content.
 */
@Component({
  selector: 'app-todo-link-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe, EmptyStateComponent, IconComponent],
  templateUrl: './todo-link-picker.component.html',
  styleUrl: './todo-link-picker.component.scss',
})
export class TodoLinkPickerComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly features = inject(FeatureService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  readonly open = model(false);
  /** The element that links: it and the elements that it links already never show. */
  readonly exclude = input<LinkEnd | null>(null);
  /** The targets the card links now (`kind:id`). */
  readonly linked = input<ReadonlySet<string>>(new Set());
  readonly picked = output<TodoLinkTarget>();

  readonly phone = mediaQuery(MEDIA.phone);
  /** The label of the Esc key, as in the global search. */
  protected readonly escLabel = isApplePlatform() ? '⎋' : 'Esc';
  /**
   * The chips of the kinds that this platform has (spec 000758). A cost centre needs a budget
   * write right (spec 001410), a Paperless document `paperless.use` and its switch
   * (§F/integrations/paperless/002766, 002767).
   */
  private readonly paperless = inject(PaperlessService);
  /** The picker asks for the part when it opens first, so a page with a closed picker sends nothing. */
  private readonly paperlessOn = toSignal(
    toObservable(this.open).pipe(
      first((open) => open),
      switchMap(() => this.paperless.linksOn()),
    ),
    { initialValue: false },
  );
  readonly chips = computed(() =>
    KIND_CHIPS.filter((chip) => {
      const feature = chip.value === 'all' ? undefined : LINK_FEATURE[chip.value];
      const allowed =
        (chip.value !== 'budget' || BUDGET_WRITE.some((p) => this.auth.can(p))) &&
        (chip.value !== 'paperless' || this.paperlessOn());
      return allowed && (feature === undefined || this.features.isOn(feature));
    }),
  );
  readonly kind = signal<PickerKind>('all');
  readonly hits = signal<readonly TodoLinkTarget[]>([]);
  readonly failed = signal(false);
  /** Paperless did not answer the newest search (§F/integrations/paperless/002766). */
  readonly paperlessDown = signal(false);

  private readonly document = inject(DOCUMENT);
  private readonly appRef = inject(ApplicationRef);
  private readonly injector = inject(Injector);
  private readonly viewContainer = inject(ViewContainerRef);
  /** The panel template; undefined before the first render. */
  private readonly pop = viewChild<TemplateRef<unknown>>('pop');
  private outlet: DomPortalOutlet | null = null;
  private host: HTMLElement | null = null;
  /** Where the focus was before the panel opened; it goes back there on close. */
  private returnFocus: HTMLElement | null = null;
  /** Stops the fade-out of a closing panel, when it opens again before the fade ends. */
  private stopLeave: (() => void) | null = null;

  readonly search = liveSearch<LinkSearch>({
    run: (q) => {
      this.failed.set(false);
      return this.api.linkSearch(q, this.kind(), this.exclude());
    },
    result: (found) => {
      this.hits.set(found.hits);
      this.paperlessDown.set(found.paperlessDown);
    },
    reset: () => {
      this.hits.set([]);
      this.paperlessDown.set(false);
      this.newest();
    },
    error: () => {
      this.hits.set([]);
      this.paperlessDown.set(false);
      this.failed.set(true);
    },
  });

  /** Without a term the kind `paperless` lists the newest documents (002766). */
  private newest(): void {
    if (this.kind() !== 'paperless') return;
    this.api
      .linkSearch('', 'paperless', this.exclude())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (found) => {
          if (this.kind() !== 'paperless' || this.search.applied()) return;
          this.hits.set(found.hits);
          this.paperlessDown.set(found.paperlessDown);
        },
        error: () => this.failed.set(true),
      });
  }

  readonly groups = computed<PickerGroup[]>(() => {
    const by = (kinds: TodoLinkKind[]) => this.hits().filter((h) => kinds.includes(h.kind));
    const all: PickerGroup[] = [
      { key: 'application', label: 'todos.picker.applications', hits: by(['application']) },
      { key: 'meeting', label: 'todos.picker.meetingsAndTops', hits: by(['meeting', 'agenda_item']) },
      { key: 'vote', label: 'todos.picker.votes', hits: by(['vote']) },
      { key: 'appointment', label: 'todos.picker.appointments', hits: by(['appointment']) },
      { key: 'gremium', label: 'todos.picker.gremien', hits: by(['gremium']) },
      { key: 'invoice', label: 'todos.picker.invoices', hits: by(['invoice']) },
      { key: 'expense', label: 'todos.picker.expenses', hits: by(['expense']) },
      { key: 'order', label: 'todos.picker.orders', hits: by(['order']) },
      { key: 'budget', label: 'todos.picker.budgets', hits: by(['budget']) },
      { key: 'ticket', label: 'todos.picker.tickets', hits: by(['ticket']) },
      { key: 'todo', label: 'todos.picker.todos', hits: by(['todo']) },
      {
        key: 'paperless',
        label: 'todos.picker.paperless',
        hits: by(['paperless']),
        note: this.paperlessDown() ? 'paperless.search.unavailable' : undefined,
      },
    ];
    return all.filter((g) => g.hits.length || g.note);
  });

  /**
   * An `open` that is true before the first render waits for the template, because the query runs
   * the effect again.
   */
  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.kind.set('all');
        this.search.clear();
        this.failed.set(false);
        this.returnFocus = this.document.activeElement as HTMLElement | null;
        queueMicrotask(() => this.panelRoot().querySelector<HTMLInputElement>('.lp__field')?.focus());
      });
    });
    effect(() => {
      const pop = this.pop();
      const floating = this.open();
      untracked(() => {
        if (!floating) this.detach();
        else if (pop) this.attach(pop);
      });
    });
    inject(DestroyRef).onDestroy(() => {
      this.stopLeave?.();
      this.dispose();
    });
  }

  /** The root of the open view: the floating panel. */
  private panelRoot(): ParentNode {
    return this.host ?? (this.viewContainer.element.nativeElement as HTMLElement);
  }

  private attach(pop: TemplateRef<unknown>): void {
    if (this.outlet) {
      this.stopLeave?.();
      return;
    }
    this.host = this.document.createElement('div');
    this.host.className = 'lp-layer';
    this.document.body.appendChild(this.host);
    this.outlet = new DomPortalOutlet(this.host, this.appRef, this.injector);
    this.outlet.attach(new TemplatePortal(pop, this.viewContainer));
  }

  /**
   * The panel closes: the focus goes back at once, the scrim and the panel fade out, and
   * only then does the layer go. The portal outlet removes its nodes at once, so the leave
   * runs here and not as an `animate.leave`. Without a running animation (reduced motion,
   * jsdom) the layer goes at once.
   */
  private detach(): void {
    if (!this.outlet || this.stopLeave) return;
    const target = this.returnFocus;
    this.returnFocus = null;
    if (target?.isConnected) target.focus?.();
    const nodes = [...(this.host?.querySelectorAll<HTMLElement>('.lp__scrim, .lp--pop') ?? [])];
    for (const n of nodes) n.classList.add('motion-fade-out');
    const running = reducedMotion() ? [] : nodes.flatMap((n) => n.getAnimations?.() ?? []);
    if (!running.length) {
      this.dispose();
      return;
    }
    let stopped = false;
    this.stopLeave = () => {
      stopped = true;
      this.stopLeave = null;
      for (const n of nodes) n.classList.remove('motion-fade-out');
    };
    const done = (): void => {
      if (stopped) return;
      this.stopLeave = null;
      this.dispose();
    };
    void Promise.all(running.map((a) => a.finished)).then(done, done);
  }

  private dispose(): void {
    this.outlet?.dispose();
    this.outlet = null;
    this.host?.remove();
    this.host = null;
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
    return linkSub(hit, this.i18n.formatLocale(), this.i18n.uiLocale(), this.t);
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
    trapTab(event, panel, { items: focusableIn(panel, 'input, button:not([disabled])') });
  }
}
