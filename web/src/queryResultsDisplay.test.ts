import { describe, expect, it } from "vitest";
import {
  extrasSummary,
  mergedEmail,
  mergedPhone,
  populatedDetailKeys,
  resultCardTitle,
  visibleResultColumns,
} from "./queryResultsDisplay";

describe("queryResultsDisplay", () => {
  it("merges phone and email from raw then norm", () => {
    expect(mergedPhone({ phone_raw: "+1 555", phone_norm: "1555" })).toBe("+1 555");
    expect(mergedPhone({ phone_norm: "1555" })).toBe("1555");
    expect(mergedEmail({ email_raw: "a@b.c", email_norm: "a@b.c" })).toBe("a@b.c");
    expect(mergedEmail({ email_norm: "a@b.c" })).toBe("a@b.c");
  });

  it("hides empty columns and absorbed duplicates from detail", () => {
    const row = {
      email_raw: "a@b.c",
      email_norm: "a@b.c",
      phone_norm: "",
      city: "Madrid",
      zip: "",
    };
    const cols = visibleResultColumns([row], { relatedView: false });
    expect(cols.map((c) => c.id)).toEqual(["email", "city"]);
    expect(populatedDetailKeys(row)).toEqual(["email_raw", "city"]);
  });

  it("includes related columns when populated", () => {
    const row = { _related_group: 1, _related_is_match: false, email_norm: "x@y.z" };
    const cols = visibleResultColumns([row], { relatedView: true });
    expect(cols.map((c) => c.id)).toContain("_related_group");
    expect(cols.map((c) => c.id)).toContain("_related_is_match");
  });

  it("builds card title from first identity", () => {
    expect(resultCardTitle({ phone_norm: "+34", email_norm: "a@b.c" })).toBe("a@b.c");
    expect(resultCardTitle({ phone_norm: "+34" })).toBe("+34");
  });

  it("summarizes extras", () => {
    expect(extrasSummary({ company: "Acme", role: "admin", site: "x" })).toEqual({
      count: 3,
      preview: "company: Acme · role: admin · …",
    });
  });
});
