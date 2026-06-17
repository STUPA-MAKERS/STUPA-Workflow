import { validateFlowGraph } from '../flow-graph.util';
import { FLOW_PRESETS } from './flow-presets';

describe('FLOW_PRESETS', () => {
  it('ships the simple + vote presets with stable keys', () => {
    expect(FLOW_PRESETS.map((p) => p.key)).toEqual(['simple', 'vote']);
    for (const preset of FLOW_PRESETS) {
      expect(typeof preset.labelKey).toBe('string');
      expect(preset.labelKey.startsWith('admin.flow.preset.')).toBe(true);
    }
  });

  it('every preset has exactly one initial state and reachable structure', () => {
    for (const preset of FLOW_PRESETS) {
      // exactly one initial state
      expect(preset.graph.states.filter((s) => s.isInitial)).toHaveLength(1);
      const errors = validateFlowGraph(preset.graph).errors;
      // The only acceptable "error" is the vote preset's empty committee seed —
      // the admin fills it in. No structural problems (dangling/unreachable/dup).
      expect(
        errors.filter((e) => !e.includes('needs a committee')),
      ).toEqual([]);
    }
  });

  it('the simple preset is fully valid out of the box', () => {
    const simple = FLOW_PRESETS.find((p) => p.key === 'simple')!;
    expect(validateFlowGraph(simple.graph)).toEqual({ valid: true, errors: [] });
  });

  it('the vote preset becomes valid once a committee is chosen', () => {
    const vote = FLOW_PRESETS.find((p) => p.key === 'vote')!;
    // empty seed → invalid (needs a committee)
    expect(validateFlowGraph(vote.graph).valid).toBe(false);
    // fill the committee → fully valid
    const filled = {
      ...vote.graph,
      states: vote.graph.states.map((s) =>
        s.kind === 'vote' ? { ...s, config: { gremiumId: 'g-real' } } : s,
      ),
    };
    expect(validateFlowGraph(filled)).toEqual({ valid: true, errors: [] });
  });

  it('the vote preset has a vote state with pass/fail branches', () => {
    const vote = FLOW_PRESETS.find((p) => p.key === 'vote')!;
    const voteState = vote.graph.states.find((s) => s.kind === 'vote');
    expect(voteState).toBeDefined();
    expect(voteState!.config).toEqual({ gremiumId: '' });
    const branches = vote.graph.transitions
      .filter((t) => t.from === 'vote')
      .map((t) => t.branch)
      .sort();
    expect(branches).toEqual(['fail', 'pass']);
  });

  it('the simple preset is a plain linear flow with no vote states', () => {
    const simple = FLOW_PRESETS.find((p) => p.key === 'simple')!;
    expect(simple.graph.states.some((s) => s.kind === 'vote')).toBe(false);
    expect(simple.graph.transitions).toHaveLength(2);
  });
});
