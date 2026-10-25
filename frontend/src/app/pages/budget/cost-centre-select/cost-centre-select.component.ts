import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  booleanAttribute,
  type AfterRenderRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import {
  anchorOutOfView,
  IconComponent,
  type IconName,
  MEDIA,
  mediaQuery,
  placeAtField,
  ScrollFadeDirective,
  showInTopLayer,
  SideSheetComponent,
  watchAnchoredPopover,
} from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { simplifyPathKey } from '@shared/budget-path';
import { nodeColors } from '../budget-color.util';
import type { BudgetTreeNode } from '../budget-tree.api';
import { formatMoney } from '@shared/format-money';
import { costCentreFigures, findBudgetNode } from '../expense-display.util';

let nextId = 0;

/** Space between the list and the edge of the viewport, in px. */
const EDGE = 8;
/** Space between the field and the list, in px. */
const GAP = 4;
/** The popover is never higher than this, in px (30rem). */
const MAX_HEIGHT = 480;
/** The popover is at least this wide, in px, so the free amounts fit beside the names. */
const MIN_WIDTH = 520;

/** The name of a cost centre, cut in three around the first hit of the search. */
interface NameParts {
  before: string;
  hit: string;
  after: string;
}

/** One cost centre in the list. */
export interface CostCentreChoice {
  id: string;
  key: string;
  name: NameParts;
  color: string | null;
  /** 0 for a top-level budget (the head of its group), else the depth below it. */
  depth: number;
  /** "2.750,00 €", or null when the tree has no figures for the fiscal year. */
  free: string | null;
  negative: boolean;
  /** The index among the choices: the keyboard moves over it. */
  index: number;
}

/** One line of a group: a choice, or the path of the choices below it (while searching). */
export type CostCentreLine =
  | { kind: 'choice'; choice: CostCentreChoice }
  | { kind: 'trail'; text: string };

/** The choices of one top-level budget. */
export interface CostCentreGroup {
  head: CostCentreChoice;
  lines: CostCentreLine[];
}

/**
 * The cost-centre field of the finance forms.
 *
 * The closed field is a filled field like `app-select`: the label, then the swatch, the
 * name and the path key of the pick in mono. The whole field opens the list. The list
 * has a search and the cost centres grouped by their top-level budget; each row shows
 * the swatch, the key, the name (the hit of the search marked) and the free amount of
 * the fiscal year (negative in the error colour). While a search runs, a line with the
 * path names the parents of the hits below it.
 *
 * - Desktop: a popover under the field, in the top layer. Phone: the shared bottom sheet.
 *   The search stays in place; only the list scrolls, in the popover and in the sheet.
 * - `allLabel` puts an extra choice with the value `''` on top of the list (for example
 *   "Alle" in a filter, "Keine" for an application). The field then names it when no cost
 *   centre is picked. An id that the tree does not hold shows as `unknownLabel`.
 * - `variant="chip"`: the trigger is a filter chip (the look of `app-filter-select`):
 *   the icon, the label and a chevron; with a pick a check mark and the name of the pick.
 * - The fiscal year of the free amount: `fiscalYearId` where the cost centre has it, else
 *   the year of its top-level budget in `fiscalYears`, else the only year it has.
 * - Keyboard: the search keeps the focus; Arrow Down/Up, Home and End move the active
 *   row (`aria-activedescendant`), Enter picks it, Escape closes and returns to the
 *   field.
 *
 * On desktop the list is a popover in the top layer, so no pane or scrolling container clips it.
 */
@Component({
  selector: 'app-cost-centre-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, NgTemplateOutlet, ScrollFadeDirective, SideSheetComponent, TranslatePipe],
  templateUrl: './cost-centre-select.component.html',
  styleUrl: './cost-centre-select.component.scss',
  host: {
    '[class.ccs--card]': "variant() === 'card'",
    '[class.ccs--chip]': "variant() === 'chip'",
  },
})
export class CostCentreSelectComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);
  private readonly i18n = inject(I18nService);

  readonly nodes = input<readonly BudgetTreeNode[]>([]);
  /** The id of the picked cost centre, or ''. */
  readonly value = input('');
  readonly label = input.required<string>();
  readonly placeholder = input('');
  readonly required = input(false, { transform: booleanAttribute });
  /** The fiscal year of the form. */
  readonly fiscalYearId = input('');
  /** The fiscal year per top-level budget, for the budgets the form has no year of. */
  readonly fiscalYears = input<ReadonlyMap<string, string>>(new Map());
  /** The text when the tree has no cost centre. */
  readonly emptyLabel = input('');
  /** The extra top choice with the value `''`, or '' for none. */
  readonly allLabel = input('');
  /** The name of a picked id that the tree does not hold. */
  readonly unknownLabel = input('');
  /**
   * `field`: a filled field like `app-select`. `card`: a larger card (a leg of a
   * transfer): the name on its own line, the path key below it, then the projected
   * content (for example the free amount after the transfer); no chevron. `chip`: a
   * filter chip.
   */
  readonly variant = input<'field' | 'card' | 'chip'>('field');
  /** The icon of the chip while nothing is picked. */
  readonly icon = input<IconName>('pie');
  /** An id for the field button, for a label outside. */
  readonly id = input(`cc-select-${nextId++}`);

  readonly picked = output<string>();
  /** The list opened. */
  readonly opened = output<void>();

  protected readonly phone = mediaQuery(MEDIA.phone);
  protected readonly open = signal(false);
  protected readonly popoverOpen = computed(() => this.open() && !this.phone());
  protected readonly sheetOpen = computed(() => this.open() && this.phone());
  /**
   * The layer of the phone sheet is in the DOM. It stays after a closing until the sheet
   * has slid out (`shown` of the sheet turns false), because a layer that goes with the
   * closing takes the sheet with it before its leave animation runs.
   */
  protected readonly sheetMounted = signal(false);
  protected readonly query = signal('');
  protected readonly active = signal(-1);
  protected readonly placed = signal(false);
  protected readonly position = signal({ top: 0, left: 0, width: 0, maxHeight: MAX_HEIGHT });

  protected readonly listId = computed(() => `${this.id()}-list`);
  protected readonly labelId = computed(() => `${this.id()}-label`);

  private readonly colors = computed(() => nodeColors([...this.nodes()]));

  /** The picked cost centre, the top choice, an unknown id, or null. */
  protected readonly pick = computed(() => {
    const id = this.value();
    if (!id) return this.allLabel() ? { name: this.allLabel(), code: '', color: null } : null;
    const node = findBudgetNode(this.nodes(), id);
    if (!node) return this.unknownLabel() ? { name: this.unknownLabel(), code: '', color: null } : null;
    return {
      name: node.name,
      code: simplifyPathKey(node.pathKey),
      color: this.colors().get(node.id) ?? null,
    };
  });

  /** The text of the chip: the name of the pick, else the label. */
  protected readonly chipText = computed(() => (this.value() ? this.pick()?.name : '') || this.label());

  /** The extra top choice, while no search runs. */
  protected readonly allChoice = computed<CostCentreChoice | null>(() =>
    this.allLabel() && !this.query().trim()
      ? {
          id: '',
          key: '',
          name: { before: this.allLabel(), hit: '', after: '' },
          color: null,
          depth: 0,
          free: null,
          negative: false,
          index: 0,
        }
      : null,
  );

  /** The groups of the list: every top-level budget with a hit, its choices below. */
  protected readonly groups = computed<CostCentreGroup[]>(() => {
    const q = this.query().trim().toLocaleLowerCase();
    const out: CostCentreGroup[] = [];
    let index = this.allChoice() ? 1 : 0;
    for (const top of this.nodes()) {
      const lines: CostCentreLine[] = [];
      let lastParent: string | null = null;
      const walk = (list: readonly BudgetTreeNode[], depth: number, trail: BudgetTreeNode[]) => {
        for (const n of list) {
          if (!q || this.matches(n, q)) {
            if (q && n.parentId !== lastParent && trail.length) {
              lines.push({
                kind: 'trail',
                text: trail.map((t) => `${t.key} ${t.name}`).join(' › '),
              });
            }
            lastParent = n.parentId;
            lines.push({ kind: 'choice', choice: this.choice(n, top, q ? 1 : depth, q, 0) });
          }
          walk(n.children ?? [], depth + 1, [...trail, n]);
        }
      };
      walk(top.children ?? [], 1, []);
      if (q && !lines.length && !this.matches(top, q)) continue;
      const head = this.choice(top, top, 0, q, index++);
      for (const line of lines) {
        if (line.kind === 'choice') line.choice.index = index++;
      }
      out.push({ head, lines });
    }
    return out;
  });

  /** Every choice in the order of the list. */
  private readonly choices = computed<CostCentreChoice[]>(() => {
    const all = this.allChoice();
    return [
      ...(all ? [all] : []),
      ...this.groups().flatMap((g) => [
        g.head,
        ...g.lines.flatMap((l) => (l.kind === 'choice' ? [l.choice] : [])),
      ]),
    ];
  });

  protected readonly activeId = computed(() => {
    const c = this.choices()[this.active()];
    return this.open() && c ? this.optionId(c) : null;
  });

  private readonly trigger = viewChild.required<ElementRef<HTMLButtonElement>>('trigger');
  private readonly menu = viewChild<ElementRef<HTMLElement>>('menu');
  private readonly layer = viewChild<ElementRef<HTMLElement>>('layer');
  private readonly sheet = viewChild(SideSheetComponent);
  private timer: ReturnType<typeof setTimeout> | null = null;
  private rendered: AfterRenderRef | null = null;

  /** A resize across the phone limit swaps the popover and the sheet, so the list closes. */
  constructor() {
    effect(() => {
      this.phone();
      untracked(() => this.close(false));
    });
    effect(() => {
      const sheet = this.sheet();
      if (sheet && !sheet.shown() && !this.sheetOpen()) untracked(() => this.sheetMounted.set(false));
    });
    watchAnchoredPopover({
      isOpen: () => this.popoverOpen(),
      inside: () => [this.host.nativeElement, this.menu()?.nativeElement],
      ownScroll: () => this.menu()?.nativeElement,
      close: () => this.close(false),
      follow: () => this.follow(),
    });
    inject(DestroyRef).onDestroy(() => this.clearTimer());
  }

  protected optionId(c: CostCentreChoice): string {
    return `${this.id()}-opt-${c.index}`;
  }

  protected toggle(): void {
    if (this.open()) this.close(true);
    else this.show();
  }

  protected onTriggerKey(event: KeyboardEvent): void {
    if (this.open()) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      this.show();
    }
  }

  protected onSearch(value: string): void {
    this.query.set(value);
    const first = this.choices().find((c) => c.depth > 0) ?? this.choices()[0];
    this.active.set(value.trim() && first ? first.index : this.startIndex());
  }

  /**
   * Keys in the search field: move in the list, pick, close.
   *
   * The field takes the Escape, so the form or the sheet around it stays open.
   */
  protected onListKey(event: KeyboardEvent): void {
    const count = this.choices().length;
    const i = this.active();
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        this.moveTo(Math.min(i + 1, count - 1));
        return;
      case 'ArrowUp':
        event.preventDefault();
        this.moveTo(Math.max(i - 1, 0));
        return;
      case 'Home':
        if (event.ctrlKey) {
          event.preventDefault();
          this.moveTo(0);
        }
        return;
      case 'End':
        if (event.ctrlKey) {
          event.preventDefault();
          this.moveTo(count - 1);
        }
        return;
      case 'Enter': {
        event.preventDefault();
        const c = this.choices()[i];
        if (c) this.choose(c);
        return;
      }
      case 'Escape':
        event.preventDefault();
        event.stopPropagation();
        this.close(true);
        return;
      case 'Tab':
        if (!this.phone()) this.close(false);
        return;
    }
  }

  protected choose(c: CostCentreChoice): void {
    if (c.id !== this.value()) this.picked.emit(c.id);
    this.close(true);
  }

  protected hover(c: CostCentreChoice): void {
    if (this.active() !== c.index) this.active.set(c.index);
  }

  protected onSheetOpen(open: boolean): void {
    if (!open) this.close(false);
  }

  private matches(n: BudgetTreeNode, q: string): boolean {
    return (
      n.name.toLocaleLowerCase().includes(q) ||
      n.key.toLocaleLowerCase().includes(q) ||
      n.pathKey.toLocaleLowerCase().includes(q)
    );
  }

  private choice(
    n: BudgetTreeNode,
    top: BudgetTreeNode,
    depth: number,
    q: string,
    index: number,
  ): CostCentreChoice {
    const at = q ? n.name.toLocaleLowerCase().indexOf(q) : -1;
    const name: NameParts =
      at >= 0
        ? {
            before: n.name.slice(0, at),
            hit: n.name.slice(at, at + q.length),
            after: n.name.slice(at + q.length),
          }
        : { before: n.name, hit: '', after: '' };
    const free = this.freeOf(n, top);
    return {
      id: n.id,
      key: n.key,
      name,
      color: this.colors().get(n.id) ?? null,
      depth,
      free: free === null ? null : formatMoney(free, this.i18n.formatLocale()),
      negative: free !== null && free < 0,
      index,
    };
  }

  /** The free amount of a cost centre in the fiscal year of the form, or null. */
  private freeOf(n: BudgetTreeNode, top: BudgetTreeNode): number | null {
    const own = this.fiscalYearId();
    const years = n.byFiscalYear ?? [];
    const fy =
      (own && years.some((f) => f.fiscalYearId === own) ? own : '') ||
      this.fiscalYears().get(top.id) ||
      ((top.byFiscalYear ?? []).length === 1 ? top.byFiscalYear[0].fiscalYearId : '');
    const figures = fy ? costCentreFigures(n, fy) : null;
    return figures ? figures.available : null;
  }

  private startIndex(): number {
    const hit = this.choices().find((c) => c.id === this.value());
    return hit ? hit.index : this.choices().length ? 0 : -1;
  }

  private moveTo(index: number): void {
    if (index < 0) return;
    this.active.set(index);
    this.reveal();
  }

  private show(): void {
    this.opened.emit();
    this.query.set('');
    this.active.set(this.startIndex());
    this.open.set(true);
    if (this.phone()) {
      this.sheetMounted.set(true);
      this.afterRender(() => {
        showInTopLayer(this.layer()?.nativeElement);
        this.later(() => this.reveal());
      });
      return;
    }
    this.placed.set(false);
    this.afterRender(() => {
      const menu = this.menu()?.nativeElement;
      if (!menu) return;
      showInTopLayer(menu);
      this.place(menu);
      this.placed.set(true);
      menu.querySelector<HTMLInputElement>('input')?.focus();
      this.reveal();
    });
  }

  private close(returnFocus: boolean): void {
    if (!this.open()) return;
    this.open.set(false);
    this.placed.set(false);
    this.active.set(-1);
    this.clearTimer();
    if (returnFocus) this.trigger().nativeElement.focus();
  }

  private reveal(): void {
    const id = this.activeId();
    const el = id ? document.getElementById(id) : null;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
  }

  /** Under the field (above it when the room below is too small), inside the viewport. */
  private place(menu: HTMLElement): void {
    this.position.set(
      placeAtField(this.trigger().nativeElement.getBoundingClientRect(), menu.scrollHeight, {
        gap: GAP,
        edge: EDGE,
        maxHeight: MAX_HEIGHT,
        minWidth: MIN_WIDTH,
      }),
    );
  }

  /** The page scrolled or resized: keep the list at its field; close it when it leaves. */
  private follow(): void {
    if (anchorOutOfView(this.trigger().nativeElement.getBoundingClientRect())) {
      this.close(false);
      return;
    }
    const menu = this.menu()?.nativeElement;
    if (menu) this.place(menu);
  }

  private later(fn: () => void): void {
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      fn();
    });
  }

  /**
   * Run `fn` after the next render, when the list that `open` adds is in the DOM. A timer
   * from the click handler is not enough: with event coalescing the change detection of
   * the click runs after that timer, so the timer finds no list and the list stays shut.
   */
  private afterRender(fn: () => void): void {
    this.clearTimer();
    this.rendered = afterNextRender(
      () => {
        this.rendered = null;
        fn();
      },
      { injector: this.injector },
    );
  }

  private clearTimer(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.rendered?.destroy();
    this.rendered = null;
  }
}
