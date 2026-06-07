/**
 * Flow-Vorlagen für den Simple-Modus (T-34). Jede Vorlage ist ein gültiger
 * `FlowGraph` (genau ein Initial, erreichbar) und dient als Startpunkt.
 */
import type { FlowGraph } from '../admin.models';
import type { TranslationKey } from '@core/i18n/translations';

export interface FlowPreset {
  key: string;
  labelKey: TranslationKey;
  graph: FlowGraph;
}

export const FLOW_PRESETS: readonly FlowPreset[] = [
  {
    key: 'simple',
    labelKey: 'admin.flow.preset.simple',
    graph: {
      states: [
        { key: 'draft', label: { de: 'Entwurf', en: 'Draft' }, category: 'open', isInitial: true },
        { key: 'submitted', label: { de: 'Eingereicht', en: 'Submitted' }, category: 'running' },
        { key: 'decided', label: { de: 'Entschieden', en: 'Decided' }, category: 'closed', editAllowed: false },
      ],
      transitions: [
        { from: 'draft', to: 'submitted', label: { de: 'Einreichen', en: 'Submit' }, actions: [] },
        { from: 'submitted', to: 'decided', label: { de: 'Entscheiden', en: 'Decide' }, actions: [] },
      ],
    },
  },
  {
    key: 'vote',
    labelKey: 'admin.flow.preset.vote',
    graph: {
      states: [
        { key: 'draft', label: { de: 'Entwurf', en: 'Draft' }, category: 'open', isInitial: true },
        { key: 'review', label: { de: 'Prüfung', en: 'Review' }, category: 'running' },
        { key: 'vote', label: { de: 'Abstimmung', en: 'Vote' }, category: 'running' },
        { key: 'decided', label: { de: 'Entschieden', en: 'Decided' }, category: 'closed', editAllowed: false },
      ],
      transitions: [
        { from: 'draft', to: 'review', label: { de: 'Einreichen', en: 'Submit' }, actions: [] },
        { from: 'review', to: 'vote', label: { de: 'Zur Abstimmung', en: 'To vote' }, actions: [{ type: 'openVote' }] },
        {
          from: 'vote',
          to: 'decided',
          label: { de: 'Auszählen', en: 'Tally' },
          guard: { voteResult: 'passed' },
          actions: [{ type: 'notify' }],
        },
      ],
    },
  },
] as const;
