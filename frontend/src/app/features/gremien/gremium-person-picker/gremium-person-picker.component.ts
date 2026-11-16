import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterRenderEffect,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import type { Observable } from 'rxjs';
import type { Uuid } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  AvatarComponent,
  SearchPillComponent,
  type FieldListPlace,
  anchorOutOfView,
  liveSearch,
  placeAtField,
  showInTopLayer,
  watchAnchoredPopover,
} from '@stupa-makers/ui-kit';
import { GremiumLogoComponent } from '../gremium-logo/gremium-logo.component';

/** A Gremium that the picker offers. */
export interface PickerGremium {
  readonly id: Uuid;
  readonly name: string;
  /** The square logo (`/api/committees/{id}/logo`), else the initials show. */
  readonly logoUrl?: string | null;
}

/** A person that the search of the picker finds. */
export interface PickerPerson {
  readonly id: Uuid;
  readonly name: string;
}

/** One hit of the picker. */
export type PickerHit =
  | { readonly kind: 'gremium'; readonly id: Uuid; readonly name: string; readonly logoUrl: string | null }
  | { readonly kind: 'person'; readonly id: Uuid; readonly name: string };

/** Space between the field and the list, in px. */
const GAP = 4;
/** The tallest the list gets, in px. */
const MAX_HEIGHT = 320;

/**
 * One search field that picks Gremien and persons (spec 001074).
 *
 * The field finds the Gremien of `gremien` by name in place, and the persons through
 * `persons` from two characters on. The hits open in a popover in the top layer, at the
 * field, so a dialog does not grow: a Gremium shows its logo, a person the avatar. A click
 * into the empty field or Arrow Down lists every Gremium, so no separate "+ Gremium"
 * button is needed. A pick emits `picked` and empties the field; the host shows the
 * chosen ones as chips and passes their ids in `taken`, so they leave the hits.
 *
 * Keyboard: Arrow Down moves into the list, the arrows move in it, Arrow Up on the first
 * hit returns to the field, Enter in the field picks the first hit, Escape closes.
 */
@Component({
  selector: 'app-gremium-person-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AvatarComponent, GremiumLogoComponent, SearchPillComponent, TranslatePipe],
  host: { '(pointerdown)': 'onPointer($event)' },
  templateUrl: './gremium-person-picker.component.html',
  styleUrl: './gremium-person-picker.component.scss',
})
export class GremiumPersonPickerComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** The text of the empty field, also its name. */
  readonly placeholder = input.required<string>();
  /** The Gremien to offer, searched by name in place. */
  readonly gremien = input<readonly PickerGremium[]>([]);
  /** The search of the persons; null offers no persons. */
  readonly persons = input<((q: string) => Observable<readonly PickerPerson[]>) | null>(null);
  /** The ids that are chosen already: they do not show as hits. */
  readonly taken = input<readonly Uuid[]>([]);

  readonly picked = output<PickerHit>();

  protected readonly listId = `gpp-${crypto.randomUUID()}`;
  /** The place of the list at the field, in viewport pixels. */
  protected readonly spot = signal<FieldListPlace | null>(null);
  protected readonly query = signal('');
  private readonly found = signal<readonly PickerPerson[]>([]);
  /** The list shows every Gremium while the field is empty (a click, Arrow Down). */
  private readonly browsing = signal(false);
  private readonly dismissed = signal(false);

  protected readonly search = liveSearch<readonly PickerPerson[]>({
    run: (q) => this.persons()?.(q),
    result: (hits) => this.found.set(hits),
    reset: () => this.found.set([]),
    error: () => this.found.set([]),
  });

  protected readonly hits = computed<readonly PickerHit[]>(() => {
    const taken = new Set(this.taken());
    const needle = this.query().trim().toLocaleLowerCase();
    const gremien = this.gremien()
      .filter((g) => !taken.has(g.id) && (needle === '' || g.name.toLocaleLowerCase().includes(needle)))
      .map((g): PickerHit => ({ kind: 'gremium', id: g.id, name: g.name, logoUrl: g.logoUrl ?? null }));
    const persons = needle === ''
      ? []
      : this.found()
          .filter((p) => !taken.has(p.id))
          .map((p): PickerHit => ({ kind: 'person', id: p.id, name: p.name }));
    return [...gremien, ...persons];
  });

  /** The query has no hit, and no search runs. */
  protected readonly none = computed(
    () => this.query().trim() !== '' && this.hits().length === 0 && !this.search.pending(),
  );

  protected readonly open = computed(
    () =>
      !this.dismissed() &&
      (this.query().trim() !== '' || this.browsing()) &&
      (this.hits().length > 0 || this.none()),
  );

  private readonly field = viewChild.required(SearchPillComponent, { read: ElementRef });
  private readonly menu = viewChild<ElementRef<HTMLElement>>('menu');

  constructor() {
    watchAnchoredPopover({
      isOpen: () => this.open(),
      inside: () => [this.host.nativeElement],
      ownScroll: () => this.menu()?.nativeElement,
      close: () => this.close(),
      follow: () => this.place(),
    });
    afterRenderEffect(() => {
      this.hits();
      const menu = this.menu()?.nativeElement;
      if (!menu) return;
      showInTopLayer(menu);
      this.place();
    });
  }

  protected onQuery(text: string): void {
    this.query.set(text);
    this.dismissed.set(false);
    this.search.set(text);
  }

  /** A press into the field lists every Gremium; a press in the list does nothing here. */
  protected onPointer(event: Event): void {
    const field = this.field().nativeElement as HTMLElement;
    if (!(event.target instanceof Node) || !field.contains(event.target)) return;
    this.browsing.set(true);
    this.dismissed.set(false);
  }

  protected onFieldKey(event: KeyboardEvent): void {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.browsing.set(true);
      this.dismissed.set(false);
      setTimeout(() => this.options()[0]?.focus());
    } else if (event.key === 'Escape' && this.open()) {
      this.close();
    } else if (event.key === 'Tab') {
      this.close();
    }
  }

  /** Enter in the field: the first hit. */
  protected onCommit(): void {
    const first = this.hits()[0];
    if (first && this.open()) this.pick(first);
    else this.search.flush();
  }

  protected onMenuKey(event: KeyboardEvent): void {
    const items = this.options();
    const index = items.indexOf(document.activeElement as HTMLElement);
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        items[Math.min(index + 1, items.length - 1)]?.focus();
        return;
      case 'ArrowUp':
        event.preventDefault();
        if (index <= 0) this.focusField();
        else items[index - 1]?.focus();
        return;
      case 'Home':
        event.preventDefault();
        items[0]?.focus();
        return;
      case 'End':
        event.preventDefault();
        items[items.length - 1]?.focus();
        return;
      case 'Escape':
        event.preventDefault();
        event.stopPropagation();
        this.close();
        this.focusField();
        return;
      case 'Tab':
        this.close();
        return;
    }
  }

  protected pick(hit: PickerHit): void {
    this.picked.emit(hit);
    this.query.set('');
    this.found.set([]);
    this.search.sync('');
    this.browsing.set(false);
    this.focusField();
  }

  protected optionId(i: number): string {
    return `${this.listId}-${i}`;
  }

  private close(): void {
    this.dismissed.set(true);
    this.browsing.set(false);
  }

  private focusField(): void {
    (this.field().nativeElement as HTMLElement).querySelector('input')?.focus();
  }

  /** At the field, as wide as it, above it when the room below is too small. */
  private place(): void {
    const menu = this.menu()?.nativeElement;
    if (!menu) return;
    const rect = (this.field().nativeElement as HTMLElement).getBoundingClientRect();
    if (anchorOutOfView(rect)) {
      this.close();
      return;
    }
    this.spot.set(placeAtField(rect, menu.scrollHeight, { gap: GAP, maxHeight: MAX_HEIGHT }));
  }

  private options(): HTMLElement[] {
    const root = document.getElementById(this.listId);
    return root ? Array.from(root.querySelectorAll<HTMLElement>('[role="option"]')) : [];
  }
}
