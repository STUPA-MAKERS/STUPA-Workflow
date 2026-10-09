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
export function allEntries(preview: RevokePreview): RevokeEntry[] {
  return [
    ...preview.gremien.map((g) => gremiumEntry(g.gremiumId)),
    ...preview.globalRoles.map((r) => roleEntry(r.roleId)),
  ];
}

/** The entries that one SSO group leads to. */
function groupEntries(preview: RevokePreview): Map<string, RevokeEntry[]> {
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
): { group: string; others: RevokeEntry[] }[] {
  const out: { group: string; others: RevokeEntry[] }[] = [];
  for (const [group, entries] of groupEntries(preview)) {
    if (!entries.includes(entry)) continue;
    const others = entries.filter((e) => e !== entry);
    if (others.length) out.push({ group, others });
  }
  return out;
}

/** The entry and every entry it reaches over shared groups (a connected component). */
function component(preview: RevokePreview, entry: RevokeEntry): Set<RevokeEntry> {
  const byGroup = [...groupEntries(preview).values()];
  const seen = new Set<RevokeEntry>([entry]);
  const todo = [entry];
  while (todo.length) {
    const cur = todo.pop()!;
    for (const entries of byGroup) {
      if (!entries.includes(cur)) continue;
      for (const e of entries) {
        if (!seen.has(e)) {
          seen.add(e);
          todo.push(e);
        }
      }
    }
  }
  return seen;
}

/** Check (`on`) or uncheck an entry together with every entry that shares a group with it. */
export function toggleEntry(
  preview: RevokePreview,
  selected: ReadonlySet<RevokeEntry>,
  entry: RevokeEntry,
  on: boolean,
): Set<RevokeEntry> {
  const next = new Set(selected);
  for (const e of component(preview, entry)) {
    if (on) next.add(e);
    else next.delete(e);
  }
  return next;
}

/** Split a selection into the ids of the request body. */
export function selectionIds(selected: ReadonlySet<RevokeEntry>): {
  gremiumIds: string[];
  globalRoleIds: string[];
} {
  const gremiumIds: string[] = [];
  const globalRoleIds: string[] = [];
  for (const e of selected) {
    if (e.startsWith('g:')) gremiumIds.push(e.slice(2));
    else globalRoleIds.push(e.slice(2));
  }
  return { gremiumIds, globalRoleIds };
}
