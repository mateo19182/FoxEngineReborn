import { appendTagFamilyFilter, appendTagFilter } from "./queryDsl";

export type QueryDslAppend = { kind: "tag"; value: string } | { kind: "family"; value: string };

export type QueryLocationState = {
  dslAppend?: QueryDslAppend;
};

export function applyQueryDslAppend(dsl: string, append: QueryDslAppend): string {
  if (append.kind === "tag") return appendTagFilter(dsl, append.value);
  return appendTagFamilyFilter(dsl, append.value);
}
