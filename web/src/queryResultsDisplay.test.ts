import { describe, expect, it } from "vitest";
import {
  isPopulated,
  populatedDetailKeys,
  resultCardTitle,
} from "./queryResultsDisplay";

describe("queryResultsDisplay", () => {
  it("treats email and phone as primary identity fields", () => {
    expect(isPopulated("a@b.c")).toBe(true);
    const row = {
      email: "a@b.c",
      phone: "",
      city: "Madrid",
    };
    expect(populatedDetailKeys(row)).toEqual(["email", "city"]);
  });

  it("hides materialized email parts when email is shown", () => {
    const row = {
      email: "a@b.c",
      email_local: "a",
      email_domain: "b.c",
      city: "Madrid",
    };
    expect(populatedDetailKeys(row)).toEqual(["email", "city"]);
  });

  it("labels related-only rows", () => {
    const row = { _related_group: 1, _related_is_match: false, email: "x@y.z" };
    expect(resultCardTitle(row)).toBe("x@y.z");
  });

  it("prefers email over phone in card title", () => {
    expect(resultCardTitle({ phone: "+34", email: "a@b.c" })).toBe("a@b.c");
    expect(resultCardTitle({ phone: "+34" })).toBe("+34");
  });
});
