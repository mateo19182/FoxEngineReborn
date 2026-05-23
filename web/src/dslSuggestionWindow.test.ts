import { describe, expect, it } from "vitest";

import { visibleSuggestionRange } from "./dslSuggestionWindow";

describe("visibleSuggestionRange", () => {
  it("returns all items when total is at most visible count", () => {
    expect(visibleSuggestionRange(2, 1)).toEqual({ start: 0, end: 2 });
  });

  it("slides the window as the active index moves down", () => {
    expect(visibleSuggestionRange(10, 0)).toEqual({ start: 0, end: 3 });
    expect(visibleSuggestionRange(10, 4)).toEqual({ start: 4, end: 7 });
    expect(visibleSuggestionRange(10, 9)).toEqual({ start: 7, end: 10 });
  });
});
