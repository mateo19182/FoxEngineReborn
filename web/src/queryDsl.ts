/** Append a tag:name clause to the current DSL (AND-combined, parenthesized). */
export function appendTagFilter(dsl: string, tagName: string): string {
  const clause = `tag:${tagName}`;
  const trimmed = dsl.trim();
  if (!trimmed) return clause;
  if (trimmed.includes(clause)) return trimmed;
  return `(${trimmed}) AND ${clause}`;
}
