export const DSL_SUGGESTION_VISIBLE_COUNT = 3;

/** Index range for the sliding window shown in the autocomplete menu. */
export function visibleSuggestionRange(
  total: number,
  activeIndex: number,
  visibleCount = DSL_SUGGESTION_VISIBLE_COUNT,
): { start: number; end: number } {
  if (total <= 0) return { start: 0, end: 0 };
  if (total <= visibleCount) return { start: 0, end: total };

  let start = activeIndex;
  if (start + visibleCount > total) {
    start = total - visibleCount;
  }
  return { start, end: start + visibleCount };
}
