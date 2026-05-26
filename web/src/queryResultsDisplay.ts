export type ResultsLayout = "table" | "cards";

export type TagLookup = Map<string, { id: string; name: string }>;

export type DisplayColumnKind = "text" | "tags" | "extras" | "related_match";

export type DisplayColumn = {
  id: string;
  label: string;
  kind: DisplayColumnKind;
  relatedOnly?: boolean;
  getValue: (row: Record<string, unknown>) => unknown;
};

/** Materialized email parts hidden when the main email column is shown. */
export const ABSORBED_ROW_KEYS = new Set(["email_local", "email_domain"]);

const DISPLAY_COLUMNS: DisplayColumn[] = [
  {
    id: "_related_group",
    label: "Group",
    kind: "text",
    relatedOnly: true,
    getValue: (row) => row._related_group,
  },
  {
    id: "_related_is_match",
    label: "Match",
    kind: "related_match",
    relatedOnly: true,
    getValue: (row) => row._related_is_match,
  },
  { id: "email", label: "Email", kind: "text", getValue: (row) => row.email },
  { id: "phone", label: "Phone", kind: "text", getValue: (row) => row.phone },
  { id: "username", label: "Username", kind: "text", getValue: (row) => row.username },
  { id: "id_card", label: "ID card", kind: "text", getValue: (row) => row.id_card },
  { id: "full_name", label: "Full name", kind: "text", getValue: (row) => row.full_name },
  { id: "first_name", label: "First name", kind: "text", getValue: (row) => row.first_name },
  { id: "last_name", label: "Last name", kind: "text", getValue: (row) => row.last_name },
  { id: "city", label: "City", kind: "text", getValue: (row) => row.city },
  { id: "country", label: "Country", kind: "text", getValue: (row) => row.country },
  { id: "address", label: "Address", kind: "text", getValue: (row) => row.address },
  { id: "zip", label: "ZIP", kind: "text", getValue: (row) => row.zip },
  { id: "dob", label: "DOB", kind: "text", getValue: (row) => row.dob },
  { id: "gender", label: "Gender", kind: "text", getValue: (row) => row.gender },
  { id: "ip", label: "IP", kind: "text", getValue: (row) => row.ip },
  { id: "user_agent", label: "User agent", kind: "text", getValue: (row) => row.user_agent },
  { id: "isp", label: "ISP", kind: "text", getValue: (row) => row.isp },
  { id: "phone_carrier", label: "Carrier", kind: "text", getValue: (row) => row.phone_carrier },
  { id: "password", label: "Password", kind: "text", getValue: (row) => row.password },
  { id: "password_hash", label: "Password hash", kind: "text", getValue: (row) => row.password_hash },
  { id: "last_seen", label: "Last seen", kind: "text", getValue: (row) => row.last_seen },
  { id: "tag_ids", label: "Tags", kind: "tags", getValue: (row) => row.tag_ids },
  { id: "extras", label: "Extras", kind: "extras", getValue: (row) => row.extras },
  { id: "ingest_ts", label: "Ingested", kind: "text", getValue: (row) => row.ingest_ts },
  { id: "batch_ref", label: "Batch", kind: "text", getValue: batchRef },
];

const TITLE_COLUMN_IDS = ["email", "phone", "username", "id_card"] as const;

const DETAIL_KEY_ORDER = [
  "_related_group",
  "_related_is_match",
  "_related_identities",
  "email",
  "email_local",
  "email_domain",
  "phone",
  "username",
  "id_card",
  "full_name",
  "first_name",
  "last_name",
  "city",
  "country",
  "address",
  "zip",
  "dob",
  "gender",
  "ip",
  "user_agent",
  "isp",
  "phone_carrier",
  "password",
  "password_hash",
  "last_seen",
  "extras",
  "tag_ids",
  "ingest_ts",
  "batch_id",
  "row_in_batch",
] as const;

export function isPopulated(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (typeof value === "boolean") return true;
  if (typeof value === "number") return !Number.isNaN(value);
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length > 0;
  return true;
}

export function formatDisplayValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function batchRef(row: Record<string, unknown>): string {
  const id = String(row.batch_id ?? "").trim();
  const short = id.length >= 8 ? id.slice(0, 8) : id;
  const rowInBatch = row.row_in_batch;
  if (rowInBatch === null || rowInBatch === undefined || short === "") return short;
  return `${short}:${String(rowInBatch)}`;
}

export function visibleResultColumns(
  rows: Record<string, unknown>[],
  options: { relatedView: boolean },
): DisplayColumn[] {
  const candidates = DISPLAY_COLUMNS.filter((col) => !col.relatedOnly || options.relatedView);
  return candidates.filter((col) => rows.some((row) => isPopulated(col.getValue(row))));
}

export function tagNamesForRow(row: Record<string, unknown>, lookup: TagLookup): string[] {
  const ids = row.tag_ids;
  if (!Array.isArray(ids)) return [];
  const names: string[] = [];
  for (const id of ids) {
    const tag = lookup.get(String(id));
    if (tag) names.push(tag.name);
  }
  return names;
}

export function extrasEntries(extras: unknown): [string, string][] {
  if (!extras || typeof extras !== "object" || Array.isArray(extras)) return [];
  return Object.entries(extras as Record<string, unknown>)
    .filter(([, value]) => isPopulated(value))
    .map(([key, value]) => [key, formatDisplayValue(value)]);
}

export function extrasSummary(extras: unknown): { count: number; preview: string } {
  const entries = extrasEntries(extras);
  if (entries.length === 0) return { count: 0, preview: "" };
  const parts = entries.slice(0, 2).map(([key, value]) => `${key}: ${value}`);
  const preview = entries.length > 2 ? `${parts.join(" · ")} · …` : parts.join(" · ");
  return { count: entries.length, preview };
}

export function resultCardTitle(row: Record<string, unknown>): string {
  for (const id of TITLE_COLUMN_IDS) {
    const col = DISPLAY_COLUMNS.find((c) => c.id === id);
    if (!col) continue;
    const value = formatDisplayValue(col.getValue(row));
    if (value) return value;
  }
  const batch = batchRef(row);
  return batch || "Lead row";
}

const CARD_SUBLINE_MAX_PARTS = 4;

export function resultCardFields(
  row: Record<string, unknown>,
  columns: DisplayColumn[],
  title: string,
): { label: string; value: string }[] {
  const fields: { label: string; value: string }[] = [];
  for (const col of columns) {
    if (col.kind === "tags" || col.kind === "extras") continue;
    if (col.kind === "related_match") continue;
    if (TITLE_COLUMN_IDS.includes(col.id as (typeof TITLE_COLUMN_IDS)[number])) {
      const value = formatDisplayValue(col.getValue(row));
      if (value === title) continue;
    }
    const value = formatDisplayValue(col.getValue(row));
    if (!value) continue;
    fields.push({ label: col.label, value });
  }
  return fields;
}

export function resultCardSubline(
  row: Record<string, unknown>,
  columns: DisplayColumn[],
  title: string,
): string {
  return resultCardFields(row, columns, title)
    .slice(0, CARD_SUBLINE_MAX_PARTS)
    .map((field) => `${field.label}: ${field.value}`)
    .join(" · ");
}

export function relatedMatchLabel(value: unknown): string {
  if (value === true) return "DSL match";
  if (value === false) return "Related only";
  return "";
}

export function populatedDetailKeys(row: Record<string, unknown>): string[] {
  const keys = Object.keys(row).filter((key) => {
    if (!isPopulated(row[key])) return false;
    if (ABSORBED_ROW_KEYS.has(key) && absorbedKeyRedundant(row, key)) return false;
    return true;
  });
  const orderIndex = new Map<string, number>(DETAIL_KEY_ORDER.map((key, index) => [key, index]));
  return keys.toSorted((a, b) => {
    const ai = orderIndex.get(a) ?? 999;
    const bi = orderIndex.get(b) ?? 999;
    if (ai !== bi) return ai - bi;
    return a.localeCompare(b);
  });
}

function absorbedKeyRedundant(row: Record<string, unknown>, key: string): boolean {
  if (key === "email_local" || key === "email_domain") {
    return isPopulated(row.email);
  }
  return false;
}

export function detailLabel(key: string): string {
  if (key === "tag_ids") return "Tags";
  if (key === "_related_is_match") return "DSL match";
  return key.replaceAll("_", " ");
}

export function formatDetailValue(
  key: string,
  value: unknown,
  tagLookup: TagLookup,
): string {
  if (key === "tag_ids") {
    return tagNamesForRow({ tag_ids: value }, tagLookup).join(", ");
  }
  if (key === "extras") {
    const entries = extrasEntries(value);
    if (entries.length === 0) return "";
    return entries.map(([k, v]) => `${k}: ${v}`).join("\n");
  }
  if (key === "_related_is_match") return relatedMatchLabel(value);
  if (key === "_related_identities" && Array.isArray(value)) {
    return value.map((item) => String(item)).join(", ");
  }
  return formatDisplayValue(value);
}
