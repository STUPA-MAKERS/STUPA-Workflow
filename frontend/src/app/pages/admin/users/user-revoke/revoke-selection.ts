import type { RevokePreview } from '../../admin.models';

/**
 * The selection of the dialog "Rechte entziehen": a set of entries, `g:<gremiumId>` for a
 * Gremium and `r:<roleId>` for a global role.
 *
 * An SSO group can lead to several entries. A revoke removes the group for all of them, so
 * the server refuses a selection that names only some (422 `revoke_incomplete`). The
 * helpers keep the selection closed: checking an entry checks every entry that shares a
 * group with it, and unchecking one unchecks all of them.
 */
export type RevokeEntry = `g:${string}` | `r:${string}`;

export function gremiumEntry(id: string): RevokeEntry {
  return `g:${id}`;
}

export function roleEntry(id: string): RevokeEntry {
  return `r:${id}`;
}

/** Every entry of the preview, Gremien first. */
export function allEntries(preview: RevokePreview): readonly RevokeEntry[] {
  return [
    ...preview.gremien.map((g) => gremiumEntry(g.gremiumId)),
    ...preview.globalRoles.map((r) => roleEntry(r.roleId)),
  ];
}

/** The entries that one SSO group leads to. */
function groupEntries(preview: RevokePreview): ReadonlyMap<string, readonly RevokeEntry[]> {
  return new Map(
    preview.groups.map((g) => [
      g.group,
      [...g.gremiumIds.map(gremiumEntry), ...g.globalRoleIds.map(roleEntry)],
    ]),
  );
}

/** The groups of one entry that also lead to another entry, with those other entries. */
export function sharedGroups(
  preview: RevokePreview,
  entry: RevokeEntry,
): readonly { readonly group: string; readonly others: readonly RevokeEntry[] }[] {
  return [...groupEntries(preview)]
    .filter(([, entries]) => entries.includes(entry))
    .map(([group, entries]) => ({ group, others: entries.filter((e) => e !== entry) }))
    .filter((g) => g.others.length > 0);
}

/**
 * The entry and every entry it reaches over shared groups (a connected component), in the
 * order of a depth-first walk that takes the last found entry next.
 */
function component(preview: RevokePreview, entry: RevokeEntry): ReadonlySet<RevokeEntry> {
  const byGroup = [...groupEntries(preview).values()];
  const visit = (
    todo: readonly RevokeEntry[],
    seen: readonly RevokeEntry[],
  ): readonly RevokeEntry[] => {
    if (todo.length === 0) return seen;
    const cur = todo[todo.length - 1];
    const found = byGroup
      .filter((entries) => entries.includes(cur))
      .flat()
      .reduce<readonly RevokeEntry[]>(
        (acc, e) => (seen.includes(e) || acc.includes(e) ? acc : [...acc, e]),
        [],
      );
    return visit([...todo.slice(0, -1), ...found], [...seen, ...found]);
  };
  return new Set(visit([entry], [entry]));
}

/** Check (`on`) or uncheck an entry together with every entry that shares a group with it. */
export function toggleEntry(
  preview: RevokePreview,
  selected: ReadonlySet<RevokeEntry>,
  entry: RevokeEntry,
  on: boolean,
): ReadonlySet<RevokeEntry> {
  const linked = component(preview, entry);
  return on
    ? new Set([...selected, ...linked])
    : new Set([...selected].filter((e) => !linked.has(e)));
}

/**
 * The selection after a reload of the preview: the entries of `kept` that still exist,
 * each checked together with the entries that now share a group with it. A new entry
 * stays unchecked, so a stale request never widens the choice of the admin.
 */
export function keptSelection(
  preview: RevokePreview,
  kept: ReadonlySet<RevokeEntry>,
): ReadonlySet<RevokeEntry> {
  const known = new Set(allEntries(preview));
  return [...kept]
    .filter((e) => known.has(e))
    .reduce<ReadonlySet<RevokeEntry>>((next, e) => toggleEntry(preview, next, e, true), new Set());
}

/** Split a selection into the ids of the request body. */
export function selectionIds(selected: ReadonlySet<RevokeEntry>): {
  readonly gremiumIds: readonly string[];
  readonly globalRoleIds: readonly string[];
} {
  const entries = [...selected];
  return {
    gremiumIds: entries.filter((e) => e.startsWith('g:')).map((e) => e.slice(2)),
    globalRoleIds: entries.filter((e) => !e.startsWith('g:')).map((e) => e.slice(2)),
  };
}
