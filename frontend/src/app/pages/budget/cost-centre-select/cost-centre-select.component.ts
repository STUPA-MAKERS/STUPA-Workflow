import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  booleanAttribute,
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
import { IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { simplifyPathKey } from '@shared/budget-path';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { mediaQuerySignal } from '../../../layout/media-query';
import { nodeColors } from '../budget-color.util';
import type { BudgetTreeNode } from '../budget-tree.api';
import { costCentreFigures, findBudgetNode, formatEur } from '../expense-display.util';

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
 * The cost-centre field of the finance forms (board "Buchung · Kostenstelle wählen").
 *
 * The closed field is a filled field like `app-select`: the label, then the swatch, the
 * name and the path key of the pick in mono. The whole field opens the list. The list
 * has a search and the cost centres grouped by their top-level budget; each row shows
 * the swatch, the key, the name (the hit of the search marked) and the free amount of
 * the fiscal year (negative in the error colour). While a search runs, a line with the
 * path names the parents of the hits below it.
 *
 * - Desktop: a popover under the field, in the top layer. Phone: the shared bottom sheet.
 * - The fiscal year of the free amount: `fiscalYearId` where the cost centre has it, else
 *   the year of its top-level budget in `fiscalYears`, else the only year it has.
 * - Keyboard: the search keeps the focus; Arrow Down/Up, Home and End move the active
 *   row (`aria-activedescendant`), Enter picks it, Escape closes and returns to the
 *   field.
 */
@Component({
  selector: 'app-cost-centre-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, NgTemplateOutlet, SideSheetComponent, TranslatePipe],
  templateUrl: './cost-centre-select.component.html',
  styleUrl: './cost-centre-select.component.scss',
  host: { '[class.ccs--card]': "variant() === 'card'" },
})
export class CostCentreSelectComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
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
  /**
   * `field`: a filled field like `app-select`. `card`: a larger card (a leg of a
   * transfer): the name on its own line, the path key below it, then the projected
   * content (for example the free amount after the transfer); no chevron.
   */
  readonly variant = input<'field' | 'card'>('field');
  /** An id for the field button, for a label outside. */
  readonly id = input(`cc-select-${nextId++}`);

  readonly picked = output<string>();
  /** The list opened. */
  readonly opened = output<void>();

  protected readonly phone = mediaQuerySignal(MEDIA.phone);
  protected readonly open = signal(false);
  protected readonly popoverOpen = computed(() => this.open() && !this.phone());
  protected readonly sheetOpen = computed(() => this.open() && this.phone());
  protected readonly query = signal('');
  protected readonly active = signal(-1);
  protected readonly placed = signal(false);
  protected readonly position = signal({ top: 0, left: 0, width: 0, maxHeight: MAX_HEIGHT });

  protected readonly listId = computed(() => `${this.id()}-list`);
  protected readonly labelId = computed(() => `${this.id()}-label`);

  private readonly colors = computed(() => nodeColors([...this.nodes()]));

  /** The picked cost centre, or null. */
  protected readonly pick = computed(() => {
    const id = this.value();
    const node = id ? findBudgetNode(this.nodes(), id) : null;
    if (!node) return null;
    return {
      name: node.name,
      code: simplifyPathKey(node.pathKey),
      color: this.colors().get(node.id) ?? null,
    };
  });

  /** The groups of the list: every top-level budget with a hit, its choices below. */
  protected readonly groups = computed<CostCentreGroup[]>(() => {
    const q = this.query().trim().toLocaleLowerCase();
    const out: CostCentreGroup[] = [];
    let index = 0;
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
            // While a search runs, the path line names the parents: the hits stand flat.
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
  private readonly choices = computed<CostCentreChoice[]>(() =>
    this.groups().flatMap((g) => [
      g.head,
      ...g.lines.flatMap((l) => (l.kind === 'choice' ? [l.choice] : [])),
    ]),
  );

  protected readonly activeId = computed(() => {
    const c = this.choices()[this.active()];
    return this.open() && c ? this.optionId(c) : null;
  });

  private readonly trigger = viewChild.required<ElementRef<HTMLButtonElement>>('trigger');
  private readonly menu = viewChild<ElementRef<HTMLElement>>('menu');
  private readonly layer = viewChild<ElementRef<HTMLElement>>('layer');
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    const inside = (root: HTMLElement | undefined, target: EventTarget | null) =>
      !!root && target instanceof Node && root.contains(target);
    const onPointer = (e: Event) => {
      if (this.popoverOpen() && !inside(this.host.nativeElement, e.target)) this.close(false);
    };
    const onViewport = (e: Event) => {
      if (this.popoverOpen() && !inside(this.menu()?.nativeElement, e.target)) this.follow();
    };
    // A resize across the phone limit swaps the popover and the sheet: close the list.
    effect(() => {
      this.phone();
      untracked(() => this.close(false));
    });
    document.addEventListener('pointerdown', onPointer, true);
    window.addEventListener('scroll', onViewport, true);
    window.addEventListener('resize', onViewport);
    inject(DestroyRef).onDestroy(() => {
      document.removeEventListener('pointerdown', onPointer, true);
      window.removeEventListener('scroll', onViewport, true);
      window.removeEventListener('resize', onViewport);
      this.clearTimer();
    });
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
    // The first hit becomes active, so Enter picks it.
    const first = this.choices().find((c) => c.depth > 0) ?? this.choices()[0];
    this.active.set(value.trim() && first ? first.index : this.startIndex());
  }

  /** Keys in the search field: move in the list, pick, close. */
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
        // The field takes the Escape: the form or the sheet around it stays open.
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
      free: free === null ? null : formatEur(free, this.i18n.locale()),
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
      this.later(() => {
        this.toTopLayer(this.layer()?.nativeElement);
        this.later(() => this.reveal());
      });
      return;
    }
    this.placed.set(false);
    this.later(() => {
      const menu = this.menu()?.nativeElement;
      if (!menu) return;
      this.toTopLayer(menu);
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

  private toTopLayer(el: HTMLElement | undefined): void {
    const pop = el as (HTMLElement & { showPopover?: () => void }) | undefined;
    if (typeof pop?.showPopover === 'function') pop.showPopover();
  }

  private reveal(): void {
    const id = this.activeId();
    const el = id ? document.getElementById(id) : null;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
  }

  /** Under the field (above it when the room below is too small), inside the viewport. */
  private place(menu: HTMLElement): void {
    const field = this.trigger().nativeElement.getBoundingClientRect();
    const below = window.innerHeight - field.bottom - GAP - EDGE;
    const above = field.top - GAP - EDGE;
    const natural = Math.min(menu.scrollHeight, MAX_HEIGHT);
    const up = natural > below && above > below;
    const maxHeight = Math.max(0, Math.min(MAX_HEIGHT, up ? above : below));
    const height = Math.min(natural, maxHeight);
    const width = Math.min(Math.max(field.width, MIN_WIDTH), window.innerWidth - 2 * EDGE);
    const left = Math.max(EDGE, Math.min(field.left, window.innerWidth - EDGE - width));
    const top = up ? field.top - GAP - height : field.bottom + GAP;
    this.position.set({ top, left, width, maxHeight });
  }

  private follow(): void {
    const rect = this.trigger().nativeElement.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
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

  private clearTimer(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}
