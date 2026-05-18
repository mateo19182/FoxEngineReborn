/** Append a tag:name clause to the current DSL (AND-combined, parenthesized). */
export function appendTagFilter(dsl: string, tagName: string): string {
  return appendDslClause(dsl, `tag:${tagName}`);
}

/** Append a tag.family clause to current DSL. */
export function appendTagFamilyFilter(dsl: string, familyCode: string): string {
  return appendDslClause(dsl, `tag.family:${familyCode}`);
}

function appendDslClause(dsl: string, clause: string): string {
  const trimmed = dsl.trim();
  if (!trimmed) return clause;
  if (trimmed.includes(clause)) return trimmed;
  return `(${trimmed}) AND ${clause}`;
}
