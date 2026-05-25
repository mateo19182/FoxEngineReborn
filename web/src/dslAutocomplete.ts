export type DslCompletionKind =
  | "start"
  | "after_lparen"
  | "after_and_or"
  | "after_not"
  | "after_clause"
  | "in_field"
  | "in_value"
  | "typing_connector";

export type DslCompletionContext = {
  kind: DslCompletionKind;
  prefix: string;
  tokenStart: number;
  tokenEnd: number;
  field?: string;
};

export type DslSuggestion = {
  label: string;
  insert: string;
  detail: string;
};

export type DslTagOption = {
  name: string;
  family: string | null;
};

export type DslFamilyOption = {
  code: string;
};

export type DslFieldSpec = {
  name: string;
  detail: string;
};

const AND_OR: { name: string; detail: string }[] = [
  { name: "AND", detail: "Both sides must match" },
  { name: "OR", detail: "Either side matches" },
];

const NOT_KW = { name: "NOT", detail: "Negate the next predicate" };

const VALUE_HINTS: Record<string, { insert: string; detail: string }[]> = {
  email: [
    { insert: "*@example.com", detail: "Substring on full email" },
    { insert: "john@outlook.com", detail: "Exact address" },
  ],
  "email.domain": [{ insert: "outlook.com", detail: "Exact domain" }],
  phone: [
    { insert: "+34*", detail: "Numbers starting with +34" },
    { insert: "*7434", detail: "Suffix match" },
  ],
  "phone.country": [{ insert: "+34", detail: "Country calling code" }],
  username: [{ insert: "john*", detail: "Prefix match" }],
  extras: [
    { insert: "*needle*", detail: "Substring in any extra column value" },
    { insert: "exact value", detail: "Exact match in any extra value" },
  ],
  tag: [],
  "tag.family": [],
  "tag.breach_date": [
    { insert: "2024", detail: "Breach year" },
    { insert: "2024-03-15", detail: "Breach date" },
  ],
};

const FIELD_TOKEN = /^[a-z_][a-z0-9_.]*$/i;
const CONNECTOR_TOKEN = /^[A-Z]+$/;
const PREDICATE_END = /[a-z_][a-z0-9_.]*:[^\s()]+$/i;
const AND_OR_END = /\b(AND|OR)\s*$/i;
const NOT_END = /\bNOT\s*$/i;
const LPAREN_END = /\(\s*$/;

function currentToken(text: string, cursor: number) {
  let tokenStart = cursor;
  while (tokenStart > 0 && !/[\s()]/.test(text[tokenStart - 1]!)) {
    tokenStart -= 1;
  }
  return {
    token: text.slice(tokenStart, cursor),
    tokenStart,
    tokenEnd: cursor,
  };
}

function trimBefore(text: string, index: number): string {
  return text.slice(0, index).replace(/\s+$/, "");
}

function isAfterCompleteClause(text: string, beforeIndex: number): boolean {
  const left = trimBefore(text, beforeIndex);
  if (!left) return false;
  if (PREDICATE_END.test(left)) return true;
  return left.endsWith(")");
}

/** Cursor context for the DSL token being edited. */
export function analyzeDslAtCursor(text: string, cursor: number): DslCompletionContext | null {
  if (cursor < 0 || cursor > text.length) return null;

  const { token, tokenStart, tokenEnd } = currentToken(text, cursor);
  const trimLeft = trimBefore(text, cursor);

  const colonIdx = token.indexOf(":");
  if (colonIdx >= 0) {
    return {
      kind: "in_value",
      field: token.slice(0, colonIdx).toLowerCase(),
      prefix: token.slice(colonIdx + 1),
      tokenStart: tokenStart + colonIdx + 1,
      tokenEnd,
    };
  }

  if (token && FIELD_TOKEN.test(token)) {
    return {
      kind: "in_field",
      prefix: token.toLowerCase(),
      tokenStart,
      tokenEnd,
    };
  }

  if (token && CONNECTOR_TOKEN.test(token)) {
    return {
      kind: "typing_connector",
      prefix: token.toUpperCase(),
      tokenStart,
      tokenEnd,
    };
  }

  if (!token) {
    if (isAfterCompleteClause(text, cursor)) {
      return { kind: "after_clause", prefix: "", tokenStart: cursor, tokenEnd: cursor };
    }
    if (AND_OR_END.test(trimLeft)) {
      return { kind: "after_and_or", prefix: "", tokenStart: cursor, tokenEnd: cursor };
    }
    if (NOT_END.test(trimLeft)) {
      return { kind: "after_not", prefix: "", tokenStart: cursor, tokenEnd: cursor };
    }
    if (trimLeft === "") {
      return { kind: "start", prefix: "", tokenStart: cursor, tokenEnd: cursor };
    }
    if (LPAREN_END.test(trimLeft)) {
      return { kind: "after_lparen", prefix: "", tokenStart: cursor, tokenEnd: cursor };
    }
  }

  return null;
}

function matchesPrefix(value: string, prefix: string): boolean {
  if (!prefix) return true;
  return value.toLowerCase().startsWith(prefix.toLowerCase());
}

function fieldSuggestions(prefix: string, fields: DslFieldSpec[]): DslSuggestion[] {
  const out: DslSuggestion[] = [];
  for (const field of fields) {
    if (!matchesPrefix(field.name, prefix)) continue;
    out.push({
      label: field.name,
      insert: `${field.name}:`,
      detail: field.detail,
    });
  }
  return out;
}

function andOrSuggestions(prefix: string): DslSuggestion[] {
  const out: DslSuggestion[] = [];
  for (const kw of AND_OR) {
    if (!matchesPrefix(kw.name, prefix)) continue;
    out.push({
      label: kw.name,
      insert: `${kw.name} `,
      detail: kw.detail,
    });
  }
  return out;
}

function connectorSuggestions(text: string, ctx: DslCompletionContext): DslSuggestion[] {
  const onlyAndOr = isAfterCompleteClause(text, ctx.tokenStart);
  const out = andOrSuggestions(ctx.prefix);
  if (!onlyAndOr && matchesPrefix(NOT_KW.name, ctx.prefix)) {
    out.push({
      label: NOT_KW.name,
      insert: `${NOT_KW.name} `,
      detail: NOT_KW.detail,
    });
  }
  return out;
}

function predicateStartSuggestions(
  kind: DslCompletionKind,
  prefix: string,
  fields: DslFieldSpec[],
): DslSuggestion[] {
  const out: DslSuggestion[] = fieldSuggestions(prefix, fields);
  const allowNot = kind === "start" || kind === "after_lparen" || kind === "after_and_or";
  if (allowNot && matchesPrefix(NOT_KW.name, prefix)) {
    out.unshift({
      label: NOT_KW.name,
      insert: `${NOT_KW.name} `,
      detail: NOT_KW.detail,
    });
  }
  return out;
}

function tagValueSuggestions(prefix: string, tags: DslTagOption[]): DslSuggestion[] {
  const out: DslSuggestion[] = [];
  for (const tag of tags) {
    if (!matchesPrefix(tag.name, prefix)) continue;
    const detail = tag.family ? `Family ${tag.family}` : "Tag name";
    out.push({ label: tag.name, insert: tag.name, detail });
  }
  return out;
}

function familyValueSuggestions(prefix: string, families: DslFamilyOption[]): DslSuggestion[] {
  const out: DslSuggestion[] = [];
  for (const family of families) {
    if (!matchesPrefix(family.code, prefix)) continue;
    out.push({
      label: family.code,
      insert: family.code,
      detail: "Tag family code",
    });
  }
  return out;
}

function valueSuggestions(
  field: string,
  prefix: string,
  tags: DslTagOption[],
  families: DslFamilyOption[],
): DslSuggestion[] {
  if (field === "tag") {
    return tagValueSuggestions(prefix, tags);
  }
  if (field === "tag.family") {
    return familyValueSuggestions(prefix, families);
  }

  const hints = VALUE_HINTS[field] ?? [];
  const out: DslSuggestion[] = [];
  for (const hint of hints) {
    if (!matchesPrefix(hint.insert, prefix)) continue;
    out.push({
      label: hint.insert,
      insert: hint.insert,
      detail: hint.detail,
    });
  }
  return out;
}

export function getDslSuggestions(
  ctx: DslCompletionContext,
  options: { tags: DslTagOption[]; families: DslFamilyOption[]; fields: DslFieldSpec[] },
  text: string,
): DslSuggestion[] {
  const { tags, families, fields } = options;
  switch (ctx.kind) {
    case "after_clause":
      return andOrSuggestions(ctx.prefix);
    case "typing_connector":
      return connectorSuggestions(text, ctx);
    case "in_field":
      return fieldSuggestions(ctx.prefix, fields);
    case "in_value":
      return valueSuggestions(ctx.field ?? "", ctx.prefix, tags, families);
    case "after_not":
      return fieldSuggestions(ctx.prefix, fields);
    case "start":
    case "after_lparen":
    case "after_and_or":
      return predicateStartSuggestions(ctx.kind, ctx.prefix, fields);
    default:
      return [];
  }
}

export function applyDslSuggestion(
  text: string,
  suggestion: DslSuggestion,
  ctx: DslCompletionContext,
): { next: string; cursor: number } {
  const before = text.slice(0, ctx.tokenStart);
  const after = text.slice(ctx.tokenEnd);
  const next = before + suggestion.insert + after;
  return { next, cursor: before.length + suggestion.insert.length };
}
