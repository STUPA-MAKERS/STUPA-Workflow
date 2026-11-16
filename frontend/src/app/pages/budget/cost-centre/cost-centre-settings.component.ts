import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  effect,
  inject,
  input,
  linkedSignal,
  output,
  type Signal,
  signal,
  untracked,
  type WritableSignal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize, type Observable } from 'rxjs';
import {
  InputComponent,
  SelectFieldComponent,
  type SelectOption,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import type { Uuid } from '@core/api/models';
import { problemCode } from '@core/api/problem';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget-tree.api';
import { ColourFieldComponent } from './colour-field.component';
import { costCentreError, keyProblem, NAME_MAX } from './cost-centre.util';

type Field = 'key' | 'name' | 'color' | 'viewGremiumId' | 'decisionGremiumId' | 'active';
type Value = string | boolean | null;

/** A change of one field of a Kostenstelle that the person made. */
interface Change {
  readonly id: Uuid;
  readonly field: Field;
  readonly value: Value;
  /** The saved value of the field when the person made the change. */
  readonly saved: Value;
}

/** The saved value of a field, in the form that a request holds. */
function savedValue(node: BudgetTreeNode, field: Field): Value {
  switch (field) {
    case 'key':
      return node.key;
    case 'name':
      return node.name;
    case 'color':
      return node.color?.trim() ?? '';
    case 'viewGremiumId':
      return node.viewGremiumId ?? null;
    case 'decisionGremiumId':
      return node.decisionGremiumId ?? null;
    case 'active':
      return node.active;
  }
}

/** A saved value with the Kostenstelle that holds it. */
interface Saved<T> {
  readonly id: string;
  readonly value: T;
}

/**
 * The settings of one Kostenstelle in the Budget tab: key, name, colour, the switch
 * "Aktiv" and its two Gremien. Each field saves when the person leaves it; `saved` then
 * tells the page to read the tree again and a toast says that the change is saved. A failed
 * save shows its reason and the field takes the saved value again.
 */
/** Save a new key or name of a Kostenstelle in a place other than the Kostenstelle itself. */
export type RenameFn = (id: Uuid, field: 'key' | 'name', value: string) => Observable<unknown>;

@Component({
  selector: 'app-cost-centre-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ColourFieldComponent,
    InputComponent,
    SelectFieldComponent,
    SwitchComponent,
  ],
  templateUrl: './cost-centre-settings.component.html',
  styleUrl: './cost-centre-settings.component.scss',
})
export class CostCentreSettingsComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly node = input.required<BudgetTreeNode>();
  readonly gremiumOptions = input<readonly SelectOption[]>([]);
  /**
   * The save of a new key or name, where the page has its own: the draft of a Haushaltsplan
   * takes them for a Kostenstelle of a Haushalt with a plan (000877).
   */
  readonly rename = input<RenameFn | null>(null);
  /** The key and the name cannot change here: in a Haushalt with a plan a draft changes them. */
  readonly textLocked = input(false);
  /** A save ended. The value says whether the server took it: the page reads the tree in both cases. */
  readonly saved = output<boolean>();
  /** The section went off the page: a component that is gone cannot emit. */
  private gone = false;

  constructor() {
    effect(() => {
      const node = this.node();
      const own = `${node.id}:`;
      const running = this.current ? `${this.current.id}:${this.current.field}` : '';
      const before = this.sent;
      this.sent = Object.fromEntries(
        Object.entries(this.sent).flatMap(([key, last]) => {
          if (!key.startsWith(own) || key === running) return [[key, last]];
          if (savedValue(node, key.slice(own.length) as Field) === last.value) return [[key, { ...last, seen: true }]];
          return last.seen || last.late ? [] : [[key, { ...last, late: true }]];
        }),
      );
      untracked(() => this.follow(node, before));
      untracked(() => this.forget());
    });
    inject(DestroyRef).onDestroy(() => {
      this.gone = true;
      this.saveText('key');
      this.saveText('name');
    });
  }

  /**
   * Show the tree value in each control whose last request left `sent` without a tree that
   * held its value, unless a change of that field waits. Such a control did not follow the
   * tree, and the tree that ends the wait can hold the same value as the tree before it.
   */
  private follow(node: BudgetTreeNode, before: typeof this.sent): void {
    const own = `${node.id}:`;
    const fields = Object.keys(before)
      .filter((key) => key.startsWith(own) && !(key in this.sent) && !before[key].seen)
      .map((key) => key.slice(own.length) as Field)
      .filter((field) => !this.waiting().some((c) => c.id === node.id && c.field === field));
    fields.forEach((field) => this.show(field, savedValue(node, field)));
  }

  /** Tell the page that a save ended, or the page that shows after this one. */
  private tell(taken = true): void {
    if (this.gone) return this.api.changed.next();
    this.saved.emit(taken);
  }

  /**
   * A field follows the saved value of its own field of its Kostenstelle, and not the node
   * object: the page reads the tree again after each save and gives a new object with the
   * same values, and a field that followed the object would then drop the text that the
   * person types in it. Another Kostenstelle gives each field its saved value, also when
   * the value is the same, because the section is one instance for every Kostenstelle.
   */
  private stored<T>(value: (node: BudgetTreeNode) => T): Signal<Saved<T>> {
    return computed(() => ({ id: this.node().id, value: value(this.node()) }), {
      equal: (a, b) => a.id === b.id && a.value === b.value,
    });
  }
  private field<T>(name: Field, value: (node: BudgetTreeNode) => T): WritableSignal<T> {
    return linkedSignal<Saved<T>, T>({
      source: this.stored(value),
      computation: (saved, last) => this.kept(name, saved, last, false),
    });
  }
  /**
   * The value of a control when its saved value or its Kostenstelle changes: what the control
   * shows, while a save runs (`busy`) or the last request is ahead of the tree. A control
   * of a Kostenstelle that the person selects again during its save shows the value of that
   * request, because the tree holds the value before, and a leave of the field would save
   * that value again. A change of the field that waits for the save counts before that
   * request, because it is the last value of the person.
   */
  private kept<T>(name: Field, saved: Saved<T>, last: { readonly source: Saved<T>; readonly value: T } | undefined, busy: boolean): T {
    const ahead = this.ahead(saved.id, name);
    if (last && last.source.id === saved.id) return busy || ahead ? last.value : saved.value;
    const waits = untracked(this.waiting).find((c) => c.id === saved.id && c.field === name);
    const value = waits ? waits.value : this.sent[`${saved.id}:${name}`]?.value;
    return waits || ahead ? ((name === 'viewGremiumId' || name === 'decisionGremiumId' ? (value ?? '') : value) as T) : saved.value;
  }
  /**
   * The last request of a field holds a value that no tree held yet. A tree that comes then
   * can be the tree of the save before, which the page reads beside this request, so the
   * control keeps what it shows and does not go back to the value of that tree.
   */
  private ahead(id: string, name: Field): boolean {
    return this.sent[`${id}:${name}`]?.seen === false;
  }
  /**
   * A switch or a select. While a save runs it keeps the choice of the person, because the
   * tree that the page reads after the first of two saves holds the first choice and not
   * the one that is on its way.
   */
  private choice<T>(name: Field, value: (node: BudgetTreeNode) => T): WritableSignal<T> {
    return linkedSignal<Saved<T>, T>({
      source: this.stored(value),
      computation: (saved, last) => this.kept(name, saved, last, untracked(this.running)),
    });
  }

  /** A save runs. */
  private readonly running = signal(false);
  readonly saving = this.running.asReadonly();
  readonly key = this.field('key', (node) => node.key);
  readonly name = this.field('name', (node) => node.name);
  readonly colour = this.field('color', (node) => node.color?.trim() ?? '');
  readonly viewGremium = this.choice('viewGremiumId', (node) => node.viewGremiumId ?? '');
  readonly decisionGremium = this.choice('decisionGremiumId', (node) => node.decisionGremiumId ?? '');
  /** The state that the switch shows: the last press, else the saved state. */
  readonly active = this.choice('active', (node) => node.active);
  readonly gremien = computed<SelectOption[]>(() => [...this.gremiumOptions()]);
  /** The error under the key: only letters and digits, at most 64 characters. */
  readonly keyError = computed(() =>
    keyProblem(this.key().trim()) ? this.i18n.translate('budget.cc.error.keyInvalid') : '',
  );
  readonly nameError = computed(() =>
    this.name().trim().length > NAME_MAX ? this.i18n.translate('budget.cc.error.nameLong') : '',
  );

  /**
   * Save the key or the name when the person leaves the field. An empty text is not saved:
   * the field shows the saved text again. A text with an error stays for the correction.
   *
   * The saved text comes back one turn later, because a field that is emptied and left in
   * the same turn has not rendered the empty text yet, and a model that goes from the saved
   * text to the saved text writes nothing into the field.
   */
  saveText(field: 'key' | 'name'): void {
    const value = this[field]().trim();
    const error = field === 'key' ? this.keyError() : this.nameError();
    if (!value) setTimeout(() => this[field].set(this.node()[field]));
    else if (!error) this.change(field, value);
  }

  saveColour(colour: string): void {
    this.change('color', colour);
  }

  saveGremium(field: 'viewGremiumId' | 'decisionGremiumId', value: string | null): void {
    (field === 'viewGremiumId' ? this.viewGremium : this.decisionGremium).set(value ?? '');
    this.change(field, value || null);
  }

  /** Save the switch "Aktiv". It stays enabled, because a disabled control loses the keyboard focus. */
  saveActive(active: boolean): void {
    this.active.set(active);
    this.change('active', active);
  }

  /** The changes that wait for the save that runs, at most one for each field of a Kostenstelle. */
  private readonly waiting = signal<readonly Change[]>([]);
  /**
   * The value that the last request for a field holds, by Kostenstelle and field. It stands
   * for the saved value from its request on, because the tree that the page reads after an
   * earlier save of the field is older than this request. `seen` says that a tree held the
   * value. A tree that holds another value after that holds it from another person, so the
   * entry then goes and the tree counts again. Without `seen`, the first tree with another
   * value after the request can be the tree of the save before (`late`), and the second one
   * holds the value of another person, so the entry goes then too. A tree that comes while the request runs says
   * nothing about it, because the page read that tree before the request ended.
   */
  private sent: Readonly<Record<string, { readonly value: Value; readonly seen: boolean; readonly late?: boolean }>> = {};

  /**
   * Take a change of a field. The changes are saved one after the other, so two writes
   * never race, and the tree that the page reads after a save is not older than that save.
   * A change that comes while a save runs waits for it, and a later change of the same
   * field takes its place: the last value of the person is the one that counts. The value
   * of the save that runs is no new change when nothing waits for its field: the leave of a
   * field and then the close of the section give the same text twice, and a refusal must
   * show its cause once.
   */
  private change(field: Field, value: Value): void {
    const node = this.node();
    const id = node.id;
    const saved = savedValue(node, field);
    const same = (c: Change): boolean => c.id === id && c.field === field;
    const runs = this.current;
    if (runs && same(runs) && runs.value === value && !this.waiting().some(same)) return;
    this.waiting.update((list) => [...list.filter((c) => c.id !== id || c.field !== field), { id, field, value, saved }]);
    this.next();
  }

  /**
   * The value that the server holds for a field as far as the page knows: the value of the
   * last request, else the saved value of the tree. For a Kostenstelle that is not the
   * selected one the page knows only its own last request, and a change then counts against
   * the saved value of the moment when the person made it.
   */
  private known(id: Uuid, field: Field): Value | undefined {
    const last = this.sent[`${id}:${field}`];
    const node = this.node();
    if (last) return last.value;
    return node.id === id ? savedValue(node, field) : undefined;
  }

  /**
   * Drop the values of the last requests for each Kostenstelle that is not the selected one
   * and has no save that runs or waits. The section cannot see the tree values of such a
   * Kostenstelle, so it cannot tell when another person changed one. When the person
   * selects it again, the tree counts.
   */
  private forget(): void {
    const selected = this.node().id;
    const busy = new Set([selected, ...(this.current ? [this.current.id] : []), ...this.waiting().map((c) => c.id)]);
    this.sent = Object.fromEntries(Object.entries(this.sent).filter(([key]) => busy.has(key.slice(0, key.lastIndexOf(':')))));
  }

  /** The change whose save runs. */
  private current: Change | null = null;

  /** Send the first change that waits, when no save runs. A change to the known value needs no request. */
  private next(): void {
    const [change, ...rest] = this.waiting();
    if (this.running() || !change) return;
    this.waiting.set(rest);
    const known = this.known(change.id, change.field);
    if (change.value === (known === undefined ? change.saved : known)) return this.next();
    this.send(change);
  }

  /** Show a value in the control of a field. */
  private show(field: Field, value: Value): void {
    switch (field) {
      case 'key':
        return this.key.set(value as string);
      case 'name':
        return this.name.set(value as string);
      case 'color':
        return this.colour.set(value as string);
      case 'viewGremiumId':
        return this.viewGremium.set((value as string | null) ?? '');
      case 'decisionGremiumId':
        return this.decisionGremium.set((value as string | null) ?? '');
      case 'active':
        return this.active.set(value as boolean);
    }
  }

  /**
   * Run the save of one change. A refused save shows its cause and the known value of its
   * field again, unless a later change of that field waits: the control then keeps that choice. The other fields keep the text that the person types in them, and so do
   * the fields of another Kostenstelle that the person selected in the meantime.
   *
   * The choices are read before the save counts as ended, because a linked signal computes
   * when it is read, and a tree that came during the save must not replace them.
   */
  private send(change: Change): void {
    const { id, field, value } = change;
    this.current = change;
    const key = `${id}:${field}`;
    const before = this.sent[key];
    this.sent = { ...this.sent, [key]: { value, seen: false } };
    this.running.set(true);
    const rename = field === 'key' || field === 'name' ? this.rename() : null;
    const request: Observable<unknown> = rename
      ? rename(id, field as 'key' | 'name', value as string)
      : this.api.updateNode(id, { [field]: value });
    request
      .pipe(
        finalize(() => {
          void [this.viewGremium(), this.decisionGremium(), this.active()];
          this.running.set(false);
          this.current = null;
          this.next();
          this.forget();
        }),
      )
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('budget.tree.toast.saved'));
          this.tell();
        },
        error: (err: unknown) => {
          this.toast.error(this.i18n.translate(costCentreError(problemCode(err))));
          this.sent = Object.fromEntries([...Object.entries(this.sent).filter(([k]) => k !== key), ...(before ? [[key, before]] : [])]);
          const known = this.known(id, field);
          const waits = this.waiting().some((c) => c.id === id && c.field === field);
          if (this.node().id === id && known !== undefined && !waits) this.show(field, known);
          this.tell(false);
        },
      });
  }
}
