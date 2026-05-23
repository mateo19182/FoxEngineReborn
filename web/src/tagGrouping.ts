export type TagRow = {
  id: string;
  name: string;
  family: string | null;
};

export function filterTags(tags: TagRow[], query: string): TagRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return tags;
  return tags.filter((t) => {
    if (t.name.toLowerCase().includes(q)) return true;
    if (t.family && t.family.toLowerCase().includes(q)) return true;
    return false;
  });
}

export function filterTagsByFamily(
  tags: TagRow[],
  familyFilter: "all" | "unassigned" | string,
): TagRow[] {
  if (familyFilter === "all") return tags;
  if (familyFilter === "unassigned") return tags.filter((t) => !t.family);
  return tags.filter((t) => t.family === familyFilter);
}

export function groupTagsByFamily(tags: TagRow[]): { family: string | null; items: TagRow[] }[] {
  const byFamily = new Map<string, TagRow[]>();
  const unassigned: TagRow[] = [];
  for (const tag of tags) {
    if (!tag.family) {
      unassigned.push(tag);
      continue;
    }
    if (!byFamily.has(tag.family)) byFamily.set(tag.family, []);
    byFamily.get(tag.family)!.push(tag);
  }
  const groups: { family: string | null; items: TagRow[] }[] = Array.from(byFamily.entries())
    .toSorted(([a], [b]) => a.localeCompare(b))
    .map(([family, items]) => ({
      family,
      items: items.toSorted((a, b) => a.name.localeCompare(b.name)),
    }));
  if (unassigned.length) {
    groups.push({
      family: null,
      items: unassigned.toSorted((a, b) => a.name.localeCompare(b.name)),
    });
  }
  return groups;
}
