import { describe, expect, it } from "vitest";

import {
  analyzeDslAtCursor,
  applyDslSuggestion,
  getDslSuggestions,
  type DslFieldSpec,
} from "./dslAutocomplete";

const TEST_FIELDS: DslFieldSpec[] = [
  { name: "email", detail: "Email" },
  { name: "phone", detail: "Phone" },
  { name: "tag", detail: "Tag" },
];

const fieldOpts = { tags: [], families: [], fields: TEST_FIELDS };

describe("analyzeDslAtCursor", () => {
  it("detects partial field names", () => {
    const dsl = "ema";
    const ctx = analyzeDslAtCursor(dsl, dsl.length);
    expect(ctx).toEqual({
      kind: "in_field",
      prefix: "ema",
      tokenStart: 0,
      tokenEnd: 3,
    });
  });

  it("detects value completion after colon", () => {
    const dsl = "tag:smok";
    const ctx = analyzeDslAtCursor(dsl, dsl.length);
    expect(ctx).toMatchObject({
      kind: "in_value",
      field: "tag",
      prefix: "smok",
      tokenStart: 4,
      tokenEnd: 8,
    });
  });

  it("detects predicate start after AND", () => {
    const dsl = "email:*@a.com AND ";
    const ctx = analyzeDslAtCursor(dsl, dsl.length);
    expect(ctx).toMatchObject({
      kind: "after_and_or",
      prefix: "",
      tokenStart: dsl.length,
      tokenEnd: dsl.length,
    });
  });

  it("detects after complete predicate", () => {
    const dsl = "email:*@a.com ";
    const ctx = analyzeDslAtCursor(dsl, dsl.length);
    expect(ctx).toMatchObject({ kind: "after_clause" });
  });
});

describe("getDslSuggestions", () => {
  it("filters fields by prefix", () => {
    const dsl = "ema";
    const ctx = analyzeDslAtCursor(dsl, dsl.length)!;
    const items = getDslSuggestions(ctx, fieldOpts, dsl);
    expect(items.some((item) => item.label === "email")).toBe(true);
    expect(items.every((item) => item.insert.endsWith(":"))).toBe(true);
  });

  it("offers only AND and OR after a complete predicate", () => {
    const dsl = "email:*@a.com ";
    const ctx = analyzeDslAtCursor(dsl, dsl.length)!;
    const items = getDslSuggestions(ctx, fieldOpts, dsl);
    expect(items.map((item) => item.label).sort()).toEqual(["AND", "OR"]);
  });

  it("offers fields after AND, not another AND", () => {
    const dsl = "email:*@a.com AND ";
    const ctx = analyzeDslAtCursor(dsl, dsl.length)!;
    const items = getDslSuggestions(ctx, fieldOpts, dsl);
    expect(items.some((item) => item.label === "AND")).toBe(false);
    expect(items.some((item) => item.insert.endsWith(":") || item.label === "NOT")).toBe(true);
  });

  it("suggests tag names for tag values", () => {
    const dsl = "tag:sm";
    const ctx = analyzeDslAtCursor(dsl, 6)!;
    const items = getDslSuggestions(
      ctx,
      {
        tags: [
          { name: "smoke-tag", family: "TEST" },
          { name: "other", family: null },
        ],
        families: [],
        fields: TEST_FIELDS,
      },
      dsl,
    );
    expect(items).toHaveLength(1);
    expect(items[0]?.label).toBe("smoke-tag");
  });
});

describe("applyDslSuggestion", () => {
  it("replaces the active token with the insert text", () => {
    const dsl = "ema";
    const ctx = analyzeDslAtCursor(dsl, dsl.length)!;
    const suggestion = getDslSuggestions(ctx, fieldOpts, dsl).find((s) => s.label === "email")!;
    const { next, cursor } = applyDslSuggestion(dsl, suggestion, ctx);
    expect(next).toBe("email:");
    expect(cursor).toBe(6);
  });

  it("keeps field prefix when completing tag values", () => {
    const dsl = "tag:sm";
    const ctx = analyzeDslAtCursor(dsl, dsl.length)!;
    const suggestion = {
      label: "smoke-tag",
      insert: "smoke-tag",
      detail: "Tag name",
    };
    const { next, cursor } = applyDslSuggestion(dsl, suggestion, ctx);
    expect(next).toBe("tag:smoke-tag");
    expect(cursor).toBe("tag:smoke-tag".length);
  });
});
