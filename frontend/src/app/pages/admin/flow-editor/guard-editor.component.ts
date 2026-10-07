import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import {
  COMPARE_OPS,
  GUARD_ACTOR_OPERATORS,
  GUARD_CONDITION_OPERATORS,
  type Guard,
  type GuardLeafOperator,
} from '../admin.models';
import { defaultGuard, guardValueKind } from './flow-guard.util';

type ValueKind = 'none' | 'role' | 'committee' | 'compare' | 'text';

/**
 * Recursive guard editor. It builds a boolean condition tree from and/or/not and leaf
 * operators such as roleIs or compare. The input and the output use the nested `Guard`
 * JSON that the server evaluator `eval_guard` already understands. A combinator shows as
 * a box with its conditions indented inside it; a condition shows its operator and the
 * value it needs (a role, a gremium, a field comparison). This is a controlled
 * component. It reads `guard` and emits a new object on every change.
 */
@Component({
  selector: 'app-guard-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    SelectComponent,
    ButtonComponent,
    IconComponent,
    InputComponent,
  ],
  templateUrl: './guard-editor.component.html',
  styleUrl: './guard-editor.component.scss',
})
export class GuardEditorComponent {
  private readonly i18n = inject(I18nService);

  readonly guard = input<Guard | null>(null);
  readonly roleOptions = input<SelectOption[]>([]);
  readonly gremiumOptions = input<SelectOption[]>([]);
  /** An automatic transition must not use an actor guard such as roleIs or isInCommittee. */
  readonly automatic = input<boolean>(false);
  readonly guardChange = output<Guard | null>();

  protected readonly compareOps = COMPARE_OPS;
  /** The comparison operators as options. The symbols need no translation. */
  protected readonly compareOpOptions: SelectOption[] = COMPARE_OPS.map((o) => ({
    value: o,
    label: o,
  }));

  /** Current operator. An empty string means no guard. */
  protected readonly op = computed<string>(() => {
    const g = this.guard();
    return g ? Object.keys(g)[0] : '';
  });

  protected readonly kind = computed<'combinator' | 'leaf' | 'none'>(() => {
    const op = this.op();
    if (!op) return 'none';
    return op === 'and' || op === 'or' || op === 'not' ? 'combinator' : 'leaf';
  });

  protected readonly children = computed<Guard[]>(() => {
    const g = this.guard();
    const op = this.op();
    if (!g || (op !== 'and' && op !== 'or' && op !== 'not')) return [];
    const v = g[op];
    return Array.isArray(v) ? (v as Guard[]) : [];
  });

  protected readonly valueKind = computed<ValueKind>(() => this.kindForOp(this.op()));

  /** What a combinator means, beside its operator: "alle Bedingungen erfüllt". */
  protected readonly combinatorText = computed(() => {
    const op = this.op();
    return op === 'and' || op === 'or' || op === 'not'
      ? this.i18n.translate(`admin.flow.guardDesc.${op}` as TranslationKey)
      : '';
  });

  protected readonly strValue = computed<string>(() => {
    const g = this.guard();
    if (!g) return '';
    const v = Object.values(g)[0];
    return v == null || typeof v === 'object' ? '' : String(v);
  });

  protected readonly cmp = computed<{ field: string; op: string; value: string }>(() => {
    const c = this.guard()?.['compare'];
    if (typeof c === 'object' && c !== null) {
      const o = c as { field?: unknown; op?: unknown; value?: unknown };
      return {
        field: String(o.field ?? ''),
        op: String(o.op ?? '=='),
        value: String(o.value ?? ''),
      };
    }
    return { field: '', op: '==', value: '' };
  });

  protected opOptions(): SelectOption[] {
    const leafs: readonly string[] = this.automatic()
      ? GUARD_CONDITION_OPERATORS
      : [...GUARD_CONDITION_OPERATORS, ...GUARD_ACTOR_OPERATORS];
    const combinators = ['and', 'or', 'not'];
    return [
      ...combinators.map((op) => ({
        value: op,
        label: this.i18n.translate(`admin.flow.guardCombinator.${op}` as TranslationKey),
      })),
      ...leafs.map((op) => ({
        value: op,
        label: this.i18n.translate(`admin.flow.guardOp.${op}` as TranslationKey),
      })),
    ];
  }

  protected onOpChange(op: string): void {
    if (!op) {
      this.guardChange.emit(null);
      return;
    }
    if (op === 'and' || op === 'or') {
      // Keep the children when the guard is already a combinator. If not, wrap the leaf.
      const existing = this.children();
      const seed = existing.length ? existing : this.guard() ? [this.guard() as Guard] : [];
      this.guardChange.emit({ [op]: seed });
      return;
    }
    if (op === 'not') {
      const existing = this.children();
      const child = existing[0] ?? (this.guard() as Guard | null) ?? this.defaultLeaf('compare');
      this.guardChange.emit({ not: [child] });
      return;
    }
    this.guardChange.emit(this.defaultLeaf(op as GuardLeafOperator));
  }

  protected addChild(): void {
    const op = this.op();
    if (op !== 'and' && op !== 'or') return;
    this.guardChange.emit({ [op]: [...this.children(), this.defaultLeaf('compare')] });
  }

  protected removeChild(index: number): void {
    const op = this.op();
    if (op !== 'and' && op !== 'or') return;
    const next = this.children().filter((_, i) => i !== index);
    this.guardChange.emit(next.length ? { [op]: next } : null);
  }

  protected setChild(index: number, child: Guard | null): void {
    const op = this.op();
    if (op !== 'and' && op !== 'or' && op !== 'not') return;
    let next = this.children().map((c, i) => (i === index ? child : c));
    next = next.filter((c): c is Guard => c !== null);
    if (op === 'not') {
      this.guardChange.emit(next.length ? { not: [next[0]] } : null);
      return;
    }
    this.guardChange.emit(next.length ? { [op]: next } : null);
  }

  protected setValue(value: string): void {
    const op = this.op();
    if (!op) return;
    this.guardChange.emit({ [op]: value });
  }

  protected setCompare(patch: Partial<{ field: string; op: string; value: string }>): void {
    this.guardChange.emit({ compare: { ...this.cmp(), ...patch } });
  }

  private kindForOp(op: string): ValueKind {
    return guardValueKind(op);
  }

  private defaultLeaf(op: GuardLeafOperator): Guard {
    return defaultGuard(op);
  }
}
