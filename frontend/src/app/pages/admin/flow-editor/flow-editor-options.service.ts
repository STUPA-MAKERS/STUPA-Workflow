import { Injectable, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import type { SelectOption } from '@stupa-makers/ui-kit';
import { type BudgetTreeNode, BudgetTreeApi } from '../../budget/budget-tree.api';
import { AdminApiService } from '../admin-api.service';
import { AdminOptionsService } from '../admin-options.service';
import {
  ACTION_TYPES,
  GUARD_ACTOR_OPERATORS,
  GUARD_CONDITION_OPERATORS,
  NOTIFY_RECIPIENT_KINDS,
  type StateKind,
} from '../admin.models';
import type { GuardLabelContext } from './flow-label.util';

/**
 * Option catalogs for the dropdowns and the guard and action labels of the flow editor.
 *
 * The component provides this service, not the root injector. Its lifetime therefore
 * matches the editor. The service swallows a load error. The affected dropdown then
 * stays empty.
 */
@Injectable()
export class FlowEditorOptionsService {
  private readonly api = inject(AdminApiService);
  private readonly options = inject(AdminOptionsService);
  private readonly budgetApi = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);

  /** Gremien for the vote-state config and for the Gremium guards and actions. */
  readonly gremiumOptions = signal<SelectOption[]>([]);
  /** Global roles for roleIs/applicantRoleIs guards. */
  readonly globalRoleOptions = signal<SelectOption[]>([]);
  /** Configured webhooks for the `webhook` action. */
  readonly webhookOptions = signal<SelectOption[]>([]);
  /** Named deadline policies a state can reference by key. */
  readonly deadlinePolicyOptions = signal<SelectOption[]>([]);
  /** Cost-center names (id maps to "name (key)") that resolve `budgetIs` guard values. */
  readonly budgetNameById = signal<ReadonlyMap<string, string>>(new Map());

  constructor() {
    this.options
      .gremiumOptions()
      .pipe(takeUntilDestroyed())
      .subscribe({ next: (o) => this.gremiumOptions.set(o), error: () => undefined });
    this.api
      .listRoles()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (roles) =>
          this.globalRoleOptions.set(
            roles.map((r) => ({ value: r.key, label: `${r.label['de'] ?? r.key} (${r.key})` })),
          ),
        error: () => undefined,
      });
    this.api
      .listWebhooks()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (hooks) =>
          this.webhookOptions.set(hooks.map((h) => ({ value: h.id, label: h.name || h.url }))),
        error: () => undefined,
      });
    this.api
      .listDeadlinePolicies()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (policies) =>
          this.deadlinePolicyOptions.set(
            policies.map((p) => ({ value: p.key, label: `${p.label['de'] ?? p.key} (${p.key})` })),
          ),
        error: () => undefined,
      });
    this.budgetApi
      .tree()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (roots) => {
          const map = new Map<string, string>();
          const walk = (nodes: BudgetTreeNode[]): void => {
            for (const n of nodes) {
              map.set(n.id, `${n.name} (${n.key})`);
              if (n.children?.length) walk(n.children);
            }
          };
          walk(roots);
          this.budgetNameById.set(map);
        },
        error: () => undefined,
      });
  }

  /** Lookup context for guard labels. It reads the option signals at call time. */
  labelContext(): GuardLabelContext {
    return {
      translate: (key) => this.i18n.translate(key),
      roleOptions: this.globalRoleOptions(),
      gremiumOptions: this.gremiumOptions(),
      budgetNameById: this.budgetNameById(),
    };
  }

  kindLabel(k: string): string {
    return this.i18n.translate(`admin.flow.kind.${k}` as TranslationKey);
  }

  kindOptions(kinds: readonly StateKind[]): SelectOption[] {
    return kinds.map((k) => ({ value: k, label: this.kindLabel(k) }));
  }

  /** Actor gates (roleIs/isInCommittee) apply to MANUAL transitions only.
   *  An automatic transition gets the condition operators only. */
  guardOpOptions(automatic: boolean | undefined): SelectOption[] {
    const ops: readonly string[] = automatic
      ? GUARD_CONDITION_OPERATORS
      : [...GUARD_CONDITION_OPERATORS, ...GUARD_ACTOR_OPERATORS];
    return ops.map((op) => ({
      value: op,
      label: this.i18n.translate(`admin.flow.guardOp.${op}` as TranslationKey),
    }));
  }

  recipientKindOptions(): SelectOption[] {
    return NOTIFY_RECIPIENT_KINDS.map((k) => ({
      value: k,
      label: this.i18n.translate(`admin.flow.recipientKind.${k}` as TranslationKey),
    }));
  }

  actionOptions(): SelectOption[] {
    return ACTION_TYPES.map((a) => ({ value: a, label: this.actionLabel(a) }));
  }

  actionLabel(type: string): string {
    return this.i18n.translate(`admin.flow.actionType.${type}` as TranslationKey);
  }

  actionDesc(type: string): string {
    return this.i18n.translate(`admin.flow.actionDesc.${type}` as TranslationKey);
  }

  guardValueHint(op: string): string {
    return this.i18n.translate(`admin.flow.guardHint.${op}` as TranslationKey);
  }
}
