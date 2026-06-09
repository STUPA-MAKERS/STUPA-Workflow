/**
 * Flow-Vorlagen (T-34). Jede Vorlage ist ein gültiger `FlowGraph` (genau ein
 * Initial, erreichbar) und dient als Startpunkt. #28-Redesign: nur normal + vote,
 * vote-State mit pass/fail-Branches.
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
        { key: 'draft', label: { de: 'Entwurf', en: 'Draft' }, color: '#4a90d9', isInitial: true },
        { key: 'submitted', label: { de: 'Eingereicht', en: 'Submitted' }, color: '#e8a33d' },
        { key: 'decided', label: { de: 'Entschieden', en: 'Decided' }, color: '#5cb85c', editAllowed: false },
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
        { key: 'draft', label: { de: 'Entwurf', en: 'Draft' }, color: '#4a90d9', isInitial: true },
        { key: 'review', label: { de: 'Prüfung', en: 'Review' }, color: '#e8a33d' },
        { key: 'vote', label: { de: 'Abstimmung', en: 'Vote' }, color: '#9b59b6', kind: 'vote', config: { gremiumId: '' } },
        { key: 'approved', label: { de: 'Angenommen', en: 'Approved' }, color: '#5cb85c', editAllowed: false },
        { key: 'rejected', label: { de: 'Abgelehnt', en: 'Rejected' }, color: '#d9534f', editAllowed: false },
      ],
      transitions: [
        { from: 'draft', to: 'review', label: { de: 'Einreichen', en: 'Submit' }, actions: [] },
        { from: 'review', to: 'vote', label: { de: 'Zur Abstimmung', en: 'To vote' }, actions: [] },
        { from: 'vote', to: 'approved', label: { de: 'Angenommen', en: 'Approved' }, branch: 'pass', actions: [] },
        { from: 'vote', to: 'rejected', label: { de: 'Abgelehnt', en: 'Rejected' }, branch: 'fail', actions: [] },
      ],
    },
  },
] as const;
