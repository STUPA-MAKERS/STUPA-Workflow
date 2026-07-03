/** Human-readable labels for states, guards and transition lists. */
import type { TranslationKey } from '@core/i18n/translations';
import type { SelectOption } from '@stupa-makers/ui-kit';
import type { FlowGraph, StateDef, TransitionDef } from '../admin.models';
import type { GuardGroup, TransitionLists } from './flow-editor.models';
import { guardValueKind } from './flow-guard.util';

export function stateDisplayLabel(s: StateDef): string {
  return s.label['de'] || s.label['en'] || s.key;
}

/** Lookup context for guard labels; values are read at call time so signal
 *  consumers stay reactive. */
export interface GuardLabelContext {
  translate: (key: TranslationKey) => string;
  roleOptions: SelectOption[];
  gremiumOptions: SelectOption[];
  budgetNameById: ReadonlyMap<string, string>;
}

function optionLabel(options: SelectOption[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value;
}

/** Resolve role key / gremium UUID / cost-centre UUID to a display name;
 *  unknown values stay visible raw. */
function resolveGuardValue(op: string, value: string, ctx: GuardLabelContext): string {
  if (!value) return value;
  const kind = guardValueKind(op);
  if (kind === 'role') return optionLabel(ctx.roleOptions, value);
  if (kind === 'committee') return optionLabel(ctx.gremiumOptions, value);
  if (op === 'budgetIs') return ctx.budgetNameById.get(value) ?? value;
  return value;
}

/**
 * Human-readable name of a guard group (operator + value; empty = catch-all).
 * Combinators use the `guardCombinator` keys, `compare` shows "field op value".
 */
export function guardGroupLabel(g: GuardGroup, ctx: GuardLabelContext): string {
  if (!g.sig) return ctx.translate('admin.flow.guardDefault');
  if (g.op === 'and' || g.op === 'or' || g.op === 'not') {
    const opLabel = ctx.translate(`admin.flow.guardCombinator.${g.op}` as TranslationKey);
    const children = (g.guard as Record<string, unknown> | null)?.[g.op];
    const n = Array.isArray(children) ? children.length : 1;
    return `${opLabel} (${n})`;
  }
  const opLabel = ctx.translate(`admin.flow.guardOp.${g.op}` as TranslationKey);
  if (g.op === 'compare') {
    const c = (g.guard as Record<string, unknown> | null)?.['compare'];
    if (c && typeof c === 'object') {
      const spec = c as { field?: unknown; op?: unknown; value?: unknown };
      const value = Array.isArray(spec.value) ? spec.value.join(', ') : String(spec.value ?? '');
      return `${String(spec.field ?? '')} ${String(spec.op ?? '==')} ${value}`.trim();
    }
    return opLabel;
  }
  const value = resolveGuardValue(g.op, g.value, ctx);
  return value ? `${opLabel}: ${value}` : opLabel;
}

/** Human-readable guard of a SINGLE transition (for the in/out lists). */
export function transitionGuardLabel(t: TransitionDef, ctx: GuardLabelContext): string {
  if (!t.guard) return ctx.translate('admin.flow.guardDefault');
  const op = Object.keys(t.guard)[0] ?? '';
  const v = Object.values(t.guard)[0];
  return guardGroupLabel(
    {
      sig: JSON.stringify(t.guard),
      guard: t.guard,
      op,
      value: v == null || typeof v === 'object' ? '' : String(v),
      indices: [],
    },
    ctx,
  );
}

/** Incoming/outgoing transitions of a state as display rows. */
export function buildTransitionLists(
  graph: FlowGraph,
  stateKey: string,
  ctx: GuardLabelContext,
): TransitionLists {
  const labelOf = new Map(graph.states.map((s) => [s.key, stateDisplayLabel(s)]));
  const rows = (match: (t: TransitionDef) => boolean) =>
    (graph.transitions ?? [])
      .map((t, index) => ({ t, index }))
      .filter(({ t }) => match(t))
      .map(({ t, index }) => ({
        index,
        from: labelOf.get(t.from) ?? t.from,
        to: labelOf.get(t.to) ?? t.to,
        label: t.label?.['de'] || t.label?.['en'] || '',
        guard: transitionGuardLabel(t, ctx),
        automatic: !!t.automatic,
        branch: t.branch ?? null,
      }));
  return {
    incoming: rows((t) => t.to === stateKey),
    outgoing: rows((t) => t.from === stateKey),
  };
}
