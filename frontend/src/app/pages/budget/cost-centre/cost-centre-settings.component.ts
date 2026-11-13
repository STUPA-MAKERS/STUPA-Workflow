import {
  ChangeDetectionStrategy,
  Component,
  computed,
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
import { BudgetTreeApi, type BudgetNodeUpdate, type BudgetTreeNode } from '../budget-tree.api';
import { BudgetPlanApi, type Side } from '../plan/budget-plan.api';
import { ColourFieldComponent } from './colour-field.component';
import { costCentreError, keyProblem, NAME_MAX } from './cost-centre.util';

/** A saved value with the Kostenstelle that holds it. */
interface Saved<T> {
  readonly id: string;
  readonly value: T;
}

/**
 * The settings of one Kostenstelle in the Budget tab: key, name, side, colour, the switch
 * "Aktiv" and its two Gremien. Each field saves when the person leaves it; `saved` then
 * tells the page to read the tree again and a toast says that the change is saved. A failed
 * save shows its reason and the field takes the saved value again.
 */
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
  private readonly planApi = inject(BudgetPlanApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly node = input.required<BudgetTreeNode>();
  /** The Kostenstelle is a direct child of a budget with a Haushaltsplan, so it has a side. */
  readonly sided = input(false);
  readonly gremiumOptions = input<readonly SelectOption[]>([]);
  readonly saved = output<void>();
  /** The side changed, so the lines of a plan can differ: the plan page reads its plan again. */
  readonly sideSaved = output<void>();

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
  private field<T>(value: (node: BudgetTreeNode) => T): WritableSignal<T> {
    return linkedSignal({ source: this.stored(value), computation: (saved) => saved.value });
  }
  /**
   * A state of the switch. While a save runs it keeps the press, because the tree that the
   * page reads after the first of two saves holds the state of the first press and not of
   * the one that is on its way.
   */
  private pressed(): WritableSignal<boolean> {
    return linkedSignal<Saved<boolean>, boolean>({
      source: this.stored((node) => node.active),
      computation: (saved, last) =>
        last && last.source.id === saved.id && untracked(this.saving) ? last.value : saved.value,
    });
  }

  /** A save runs. */
  readonly saving = signal(false);
  readonly key = this.field((node) => node.key);
  readonly name = this.field((node) => node.name);
  readonly colour = this.field((node) => node.color?.trim() ?? '');
  readonly side = this.field<Side | null>((node) => node.side ?? null);
  readonly viewGremium = this.field((node) => node.viewGremiumId ?? '');
  readonly decisionGremium = this.field((node) => node.decisionGremiumId ?? '');
  /** The state that the switch shows: the last press, else the saved state. */
  readonly active = this.pressed();
  /** The state that the last request for the switch holds. */
  private readonly sentActive = this.pressed();
  readonly gremien = computed<SelectOption[]>(() => [...this.gremiumOptions()]);
  /** The error under the key: only letters and digits, at most 64 characters. */
  readonly keyError = computed(() =>
    keyProblem(this.key().trim()) ? this.i18n.translate('budget.cc.error.keyInvalid') : '',
  );
  readonly nameError = computed(() =>
    this.name().trim().length > NAME_MAX ? this.i18n.translate('budget.cc.error.nameLong') : '',
  );
  readonly sides = computed<SelectOption[]>(() => [
    { value: 'income', label: this.i18n.translate('budget.plan.side.income') },
    { value: 'expense', label: this.i18n.translate('budget.plan.side.expense') },
  ]);

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
    else if (!error && value !== this.node()[field]) this.save({ [field]: value });
  }

  saveColour(colour: string): void {
    if (colour !== (this.node().color?.trim() ?? '')) this.save({ color: colour });
  }

  saveGremium(field: 'viewGremiumId' | 'decisionGremiumId', value: string | null): void {
    if ((value || null) === (this.node()[field] ?? null)) return;
    (field === 'viewGremiumId' ? this.viewGremium : this.decisionGremium).set(value ?? '');
    this.save({ [field]: value || null });
  }

  /** Save the side. A refused change shows the saved side again. */
  saveSide(side: string | null): void {
    if (!side || side === this.node().side) return;
    this.side.set(side as Side);
    this.run(this.node().id, this.planApi.setSide(this.node().id, side as Side), ['side'], true);
  }

  save(patch: BudgetNodeUpdate): void {
    this.run(this.node().id, this.api.updateNode(this.node().id, patch), Object.keys(patch));
  }

  /** The press of the switch that waits for the save that runs, with its Kostenstelle. */
  private readonly waiting = signal<{ readonly id: Uuid; readonly active: boolean } | null>(null);

  /**
   * Save the switch "Aktiv". A press while a save runs waits for it, so two writes never
   * race and the last press is the one that counts. The switch stays enabled, because a
   * disabled control loses the keyboard focus.
   */
  saveActive(active: boolean): void {
    this.active.set(active);
    if (this.saving()) return this.waiting.set({ id: this.node().id, active });
    if (active === this.sentActive()) return;
    this.sentActive.set(active);
    this.save({ active });
  }

  /**
   * A save ended: send the press of the switch that waited for it, to the Kostenstelle that
   * the person pressed it for, also when another one is selected now. The two states of the
   * switch are read before the save counts as ended, because a linked signal computes when
   * it is read, and a tree that came during the save must not replace them.
   */
  private ended(): void {
    const waiting = this.waiting();
    this.active();
    this.sentActive();
    this.waiting.set(null);
    this.saving.set(false);
    if (!waiting) return;
    if (waiting.id === this.node().id) return this.saveActive(waiting.active);
    this.run(waiting.id, this.api.updateNode(waiting.id, { active: waiting.active }), ['active']);
  }

  /** Show the saved values of the fields of a refused save again. */
  private reset(fields: readonly string[]): void {
    const node = this.node();
    if (fields.includes('key')) this.key.set(node.key);
    if (fields.includes('name')) this.name.set(node.name);
    if (fields.includes('color')) this.colour.set(node.color?.trim() ?? '');
    if (fields.includes('side')) this.side.set(node.side ?? null);
    if (fields.includes('viewGremiumId')) this.viewGremium.set(node.viewGremiumId ?? '');
    if (fields.includes('decisionGremiumId')) this.decisionGremium.set(node.decisionGremiumId ?? '');
    if (fields.includes('active')) this.active.set(node.active);
    if (fields.includes('active')) this.sentActive.set(node.active);
  }

  /**
   * Run a save. A refused save shows its cause and the saved value of the `fields` that it
   * held. The other fields keep the text that the person types in them, and so do the
   * fields of another Kostenstelle that the person selected in the meantime.
   */
  private run(id: Uuid, request: Observable<unknown>, fields: readonly string[], side = false): void {
    this.saving.set(true);
    request.pipe(finalize(() => this.ended())).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.saved'));
        this.saved.emit();
        if (side) this.sideSaved.emit();
      },
      error: (err: unknown) => {
        this.toast.error(this.i18n.translate(costCentreError(problemCode(err))));
        if (this.node().id === id) this.reset(fields);
        this.saved.emit();
      },
    });
  }
}
