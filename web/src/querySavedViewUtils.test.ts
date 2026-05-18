import { describe, expect, it } from "vitest";

import { applySavedViewToQuery } from "./querySavedViewUtils";

describe("applySavedViewToQuery", () => {
  it("applies dsl and view for manual run flows", () => {
    const out = applySavedViewToQuery({
      dsl: "email:*@example.com",
      view: "related",
    });

    expect(out).toEqual({
      dsl: "email:*@example.com",
      view: "related",
    });
  });
});
