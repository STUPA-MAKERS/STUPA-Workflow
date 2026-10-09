import type { RevokeGremium, RevokePreview } from '../../admin.models';
import {
  allEntries,
  gremiumEntry,
  keptSelection,
  roleEntry,
  selectionIds,
  sharedGroups,
  toggleEntry,
  type RevokeEntry,
} from './revoke-selection';

function gremium(id: string): RevokeGremium {
  return {
    gremiumId: id,
    name: id,
    membership: null,
    groups: [],
    assignments: [],
    poolEntries: [],
    plannedDelegations: [],
    liveDelegations: [],
    openTasks: 0,
  };
}

/** g-a and g-b share "both"; g-b and r-1 share "chain"; g-c stands alone. */
const PREVIEW: RevokePreview = {
  principal: { id: 'p', displayName: 'P', email: null, lastLogin: null, active: true },
  gremien: [gremium('g-a'), gremium('g-b'), gremium('g-c')],
  globalRoles: [{ roleId: 'r-1', roleKey: 'k', roleLabel: {}, groups: ['chain'], assignments: [] }],
  groups: [
    { group: 'both', gremiumIds: ['g-a', 'g-b'], globalRoleIds: [] },
    { group: 'chain', gremiumIds: ['g-b'], globalRoleIds: ['r-1'] },
    { group: 'solo', gremiumIds: ['g-c'], globalRoleIds: [] },
  ],
  isSelf: false,
};

describe('revoke selection', () => {
  it('names the entries, Gremien first', () => {
    expect(gremiumEntry('x')).toBe('g:x');
    expect(roleEntry('y')).toBe('r:y');
    expect(allEntries(PREVIEW)).toEqual(['g:g-a', 'g:g-b', 'g:g-c', 'r:r-1']);
  });

  it('lists the groups an entry shares with other entries', () => {
    expect(sharedGroups(PREVIEW, 'g:g-b')).toEqual([
      { group: 'both', others: ['g:g-a'] },
      { group: 'chain', others: ['r:r-1'] },
    ]);
    // A group of one entry is not shared.
    expect(sharedGroups(PREVIEW, 'g:g-c')).toEqual([]);
  });

  it('keeps the choice of the admin on a reload, closed over shared groups', () => {
    // g-c stays alone; g-a now pulls g-b and r-1 in; a gone entry drops out.
    const kept = keptSelection(PREVIEW, new Set<RevokeEntry>(['g:g-a', 'g:gone']));
    expect([...kept].sort()).toEqual(['g:g-a', 'g:g-b', 'r:r-1']);
    expect([...keptSelection(PREVIEW, new Set<RevokeEntry>(['g:g-c']))]).toEqual(['g:g-c']);
    expect(keptSelection(PREVIEW, new Set()).size).toBe(0);
  });

  it('checks and unchecks the whole connected set', () => {
    const on = toggleEntry(PREVIEW, new Set(), 'g:g-a', true);
    expect([...on].sort()).toEqual(['g:g-a', 'g:g-b', 'r:r-1']);
    const off = toggleEntry(PREVIEW, new Set(allEntries(PREVIEW)), 'r:r-1', false);
    expect([...off]).toEqual(['g:g-c']);
    // A lone entry changes alone.
    expect([...toggleEntry(PREVIEW, new Set(), 'g:g-c', true)]).toEqual(['g:g-c']);
  });

  it('splits the selection into the ids of the request', () => {
    const sel = new Set<RevokeEntry>(['g:g-a', 'r:r-1', 'g:g-c']);
    expect(selectionIds(sel)).toEqual({ gremiumIds: ['g-a', 'g-c'], globalRoleIds: ['r-1'] });
  });
});
