import { useMemo, useRef, useState } from "react";
import { api, getToken, onUnauthorized } from "./api";
import { DocTip } from "./DocTip";

const COLUMN_MAP_SAMPLE_ROW_COUNT = 5;
const COLUMN_MAP_DISCARD_VALUE = "__discard__";

const FALLBACK_CANONICAL_FIELDS = [
  "phone",
  "email",
  "username",
  "id_card",
  "full_name",
  "first_name",
  "last_name",
  "dob",
  "gender",
  "address",
  "city",
  "country",
  "zip",
  "ip",
  "user_agent",
  "isp",
  "phone_carrier",
  "password",
  "password_hash",
  "last_seen",
];

type IngestItem = {
  batch_id: string;
  job_id: string;
  inner_name: string;
  format: string;
  detect_confidence?: number;
};

type IngestResponse = {
  batch_id?: string;
  job_id?: string;
  items: IngestItem[];
};

type ColumnGuess = {
  field: string;
  confidence: number;
};

type PreviewFile = {
  inner_name: string;
  format: string;
  format_confidence?: number;
  csv_delimiter?: string | null;
  headers?: string[] | null;
  column_guesses?: Record<string, ColumnGuess[]>;
  recommended_column_map?: Record<string, string>;
  sample_rows?: Record<string, string>[];
  size?: number;
};

type PreviewResponse = {
  upload_id: string;
  outer_filename: string;
  merge_archive: boolean;
  file_count: number;
  canonical_fields?: string[];
  files: PreviewFile[];
};

type ColumnMapSuggestResponse = {
  column_map: Record<string, string>;
  canonical_fields: string[];
};

type TagOption = {
  id: string;
  name: string;
  type: string | null;
  family: string | null;
};

function buildColumnMapByFileJson(selections: Record<string, Record<string, string>>): string {
  const mappedByFile = Object.fromEntries(
    Object.entries(selections).map(([innerName, fileSelections]) => [
      innerName,
      Object.fromEntries(
        Object.entries(fileSelections).filter(([, value]) => value.trim() !== ""),
      ),
    ]),
  );
  return JSON.stringify(mappedByFile, null, 2);
}

function bestGuessFor(file: PreviewFile, header: string): ColumnGuess | null {
  const recommended = file.recommended_column_map?.[header];
  if (recommended) {
    const match = file.column_guesses?.[header]?.find((guess) => guess.field === recommended);
    return { field: recommended, confidence: match?.confidence ?? 1 };
  }
  return file.column_guesses?.[header]?.[0] ?? null;
}

function isDiscardSelection(value: string | undefined): boolean {
  return value === COLUMN_MAP_DISCARD_VALUE;
}

function confidenceLabel(value: number | undefined): string {
  if (value === undefined) return "";
  return `${Math.round(value * 100)}%`;
}

function formatBytes(value: number | undefined): string {
  if (value === undefined) return "";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let next = value / 1024;
  for (const unit of units) {
    if (next < 1024 || unit === units.at(-1)) return `${next.toFixed(next >= 10 ? 0 : 1)} ${unit}`;
    next /= 1024;
  }
  return `${value} B`;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function IngestPage() {
  const [mergeArchive, setMergeArchive] = useState(false);
  const [tagNames, setTagNames] = useState("");
  const [batchName, setBatchName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const columnMapJsonRef = useRef("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<PreviewResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [suggestingInnerName, setSuggestingInnerName] = useState<string | null>(null);
  const [tags, setTags] = useState<TagOption[]>([]);
  const [tagsLoaded, setTagsLoaded] = useState(false);
  const [tagSuggestionsOpen, setTagSuggestionsOpen] = useState(false);
  const [columnSelectionsByFile, setColumnSelectionsByFile] = useState<
    Record<string, Record<string, string>>
  >({});
  const [selectedFileNames, setSelectedFileNames] = useState<string[]>([]);

  const canonicalFields = previewData?.canonical_fields?.length
    ? previewData.canonical_fields
    : FALLBACK_CANONICAL_FIELDS;
  const selectedFileNameSet = useMemo(() => new Set(selectedFileNames), [selectedFileNames]);
  const csvPreviewFiles =
    previewData?.files.filter(
      (item) =>
        !mergeArchive &&
        selectedFileNameSet.has(item.inner_name) &&
        item.format === "csv" &&
        item.headers?.length,
    ) ?? [];
  const canChooseArchiveMembers = (previewData?.files.length ?? 0) > 1;
  const canMergeSelectedFiles = canChooseArchiveMembers && selectedFileNames.length > 1;
  const selectedTagNames = useMemo(
    () => tagNames.split(",").flatMap((tag) => {
      const trimmed = tag.trim();
      return trimmed ? [trimmed] : [];
    }),
    [tagNames],
  );
  const currentTagQuery = tagNames.includes(",") ? (tagNames.split(",").at(-1) ?? "").trim() : tagNames.trim();
  const tagSuggestions = useMemo(() => {
    const q = currentTagQuery.toLowerCase();
    const qPattern = q ? new RegExp(escapeRegExp(q)) : null;
    const selected = new Set(selectedTagNames.map((tag) => tag.toLowerCase()));
    const out: TagOption[] = [];
    for (const tag of tags) {
      const name = tag.name.toLowerCase();
      if (selected.has(name) || (qPattern && !qPattern.test(name))) continue;
      out.push(tag);
      if (out.length >= 12) break;
    }
    return out;
  }, [currentTagQuery, selectedTagNames, tags]);
  const primaryBusy = loading || previewLoading;
  const primaryLabel = previewData
    ? loading
      ? "Queueing..."
      : "Queue ingest"
    : previewLoading
      ? "Previewing..."
      : "Preview detection";

  function updateColumnSelections(next: Record<string, Record<string, string>>) {
    setColumnSelectionsByFile(next);
    columnMapJsonRef.current = buildColumnMapByFileJson(next);
  }

  function resetPreviewState() {
    setPreviewData(null);
    setColumnSelectionsByFile({});
    setSelectedFileNames([]);
    setMergeArchive(false);
    columnMapJsonRef.current = "";
  }

  function handleFileChange(nextFile: File | null) {
    setSelectedFile(nextFile);
    setErr(null);
    setMsg(null);
    resetPreviewState();
  }

  function clearSelectedFile() {
    setSelectedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    setErr(null);
    setMsg(null);
    resetPreviewState();
  }

  function toggleSelectedFile(name: string, selected: boolean) {
    const next = selected
      ? Array.from(new Set([...selectedFileNames, name]))
      : selectedFileNames.filter((item) => item !== name);
    setSelectedFileNames(next);
    if (next.length <= 1) setMergeArchive(false);
  }

  async function loadTags() {
    if (tagsLoaded) return;
    const data = await api<TagOption[]>("/tags");
    setTags(data);
    setTagsLoaded(true);
  }

  function addTagName(name: string) {
    const parts = tagNames.split(",");
    parts[parts.length - 1] = name;
    const next = parts.flatMap((part) => {
      const trimmed = part.trim();
      return trimmed ? [trimmed] : [];
    });
    setTagNames(`${Array.from(new Set(next)).join(", ")}, `);
    setTagSuggestionsOpen(false);
  }

  function removeTagName(name: string) {
    setTagNames(selectedTagNames.filter((tag) => tag !== name).join(", "));
  }

  async function previewDetection() {
    setErr(null);
    setMsg(null);
    setPreviewData(null);
    if (!selectedFile) {
      setErr("Choose a file for preview");
      return;
    }
    const token = getToken();
    if (!token) {
      setErr("Not logged in");
      return;
    }
    setPreviewLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", selectedFile);
      const r = await fetch("/api/ingest/preview", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const text = await r.text();
      if (!r.ok) {
        onUnauthorized(r.status, true);
        throw new Error(text || r.statusText);
      }
      const data = JSON.parse(text) as PreviewResponse;
      const nextSelections: Record<string, Record<string, string>> = {};
      for (const item of data.files ?? []) {
        if (item.format !== "csv") continue;
        const fileSelections: Record<string, string> = {};
        for (const header of item.headers ?? []) {
          if (!header) continue;
          fileSelections[header] = item.recommended_column_map?.[header] ?? "";
        }
        nextSelections[item.inner_name] = fileSelections;
      }
      setPreviewData(data);
      setSelectedFileNames((data.files ?? []).map((item) => item.inner_name));
      setColumnSelectionsByFile(nextSelections);
      columnMapJsonRef.current = buildColumnMapByFileJson(nextSelections);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function suggestColumnMap(filePreview: PreviewFile) {
    const headers = filePreview.headers ?? [];
    if (!headers.length) return;
    setErr(null);
    setMsg(null);
    setSuggestingInnerName(filePreview.inner_name);
    try {
      const data = await api<ColumnMapSuggestResponse>("/ingest/suggest-column-map", {
        method: "POST",
        json: {
          format: "csv",
          inner_name: filePreview.inner_name,
          headers,
          sample_rows: filePreview.sample_rows ?? [],
        },
      });
      const currentFileSelections = columnSelectionsByFile[filePreview.inner_name] ?? {};
      const mergedSelections = { ...currentFileSelections };
      for (const [header, targetField] of Object.entries(data.column_map)) {
        if (isDiscardSelection(currentFileSelections[header])) continue;
        mergedSelections[header] = targetField;
      }
      updateColumnSelections({
        ...columnSelectionsByFile,
        [filePreview.inner_name]: {
          ...mergedSelections,
        },
      });
      setMsg(`Local LLM suggested ${Object.keys(data.column_map).length} CSV mappings.`);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSuggestingInnerName(null);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!previewData) {
      await previewDetection();
      return;
    }
    setErr(null);
    setMsg(null);
    if (!selectedFileNames.length) {
      setErr("Choose at least one file to import");
      return;
    }
    setLoading(true);
    try {
      const columnMapJson = columnMapJsonRef.current;
      const data = await api<IngestResponse>("/ingest/file/from-upload", {
        method: "POST",
        json: {
          upload_id: previewData.upload_id,
          selected_files: selectedFileNames,
          tag_names: tagNames,
          merge_archive: mergeArchive,
          ...(batchName.trim() ? { batch_name: batchName.trim() } : {}),
          ...(columnMapJson.trim() && !mergeArchive
            ? { column_map_by_file_json: columnMapJson.trim() }
            : {}),
        },
      });
      const items = data.items ?? [];
      if (items.length === 1) {
        setMsg(`Queued job ${items[0].job_id} (${items[0].format}). Check Jobs.`);
      } else {
        setMsg(`Queued ${items.length} ingest jobs. First job ${items[0]?.job_id}. Check Jobs.`);
      }
      setTagNames("");
      setBatchName("");
      clearSelectedFile();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Ingest file</h1>
          <p className="lead">
            Preview every upload, review CSV column matches when needed, then queue the ingest job.
          </p>
        </div>
      </header>

      <section className="panel">
        <p className="hint" style={{ marginTop: 0 }}>
          Supports JSONL, CSV, combo lines, and archives. The file is uploaded once during preview, then
          queued from the stored upload after you confirm the detected contents.
        </p>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="ing-file">File</label>
            <div className="file-picker">
              <input
                ref={fileInputRef}
                id="ing-file"
                type="file"
                className="file-picker__input"
                onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
              />
              <button
                type="button"
                className="secondary file-picker__btn"
                onClick={() => fileInputRef.current?.click()}
              >
                Choose file
              </button>
              <span
                className={`file-picker__name${selectedFile ? " file-picker__name--chosen" : ""}`}
                title={selectedFile?.name}
              >
                {selectedFile?.name ?? "No file selected"}
              </span>
              {selectedFile ? (
                <button type="button" className="link-btn file-picker__clear" onClick={clearSelectedFile}>
                  Clear
                </button>
              ) : null}
            </div>
          </div>
          <div className="field">
            <label htmlFor="ing-tags">Tag names (comma-separated, created if missing)</label>
            <div className="tag-autocomplete">
              <input
                id="ing-tags"
                value={tagNames}
                onChange={(e) => {
                  setTagNames(e.target.value);
                  setTagSuggestionsOpen(true);
                }}
                onFocus={() => {
                  setTagSuggestionsOpen(true);
                  void loadTags().catch((ex) => setErr(String(ex)));
                }}
                onBlur={() => setTagSuggestionsOpen(false)}
                placeholder="Start typing or pick existing tags"
                autoComplete="off"
              />
              {tagSuggestionsOpen && (tagSuggestions.length > 0 || tagsLoaded) ? (
                <div className="tag-autocomplete__menu">
                  {tagSuggestions.length > 0 ? (
                    tagSuggestions.map((tag) => (
                      <button
                        key={tag.id}
                        type="button"
                        className="tag-autocomplete__option"
                        onMouseDown={(event) => {
                          event.preventDefault();
                          addTagName(tag.name);
                        }}
                      >
                        <span>{tag.name}</span>
                        {tag.type || tag.family ? (
                          <span className="muted">
                            {tag.type ? tag.type : ""}
                            {tag.type && tag.family ? " · " : ""}
                            {tag.family ? tag.family : ""}
                          </span>
                        ) : null}
                      </button>
                    ))
                  ) : (
                    <div className="tag-autocomplete__empty">No existing tags match.</div>
                  )}
                </div>
              ) : null}
            </div>
            {selectedTagNames.length ? (
              <div className="ingest-tag-chips">
                {selectedTagNames.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    className="ingest-tag-chip"
                    onClick={() => removeTagName(tag)}
                    title={`Remove ${tag}`}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="ing-batch">Batch name (optional)</label>
            <input id="ing-batch" value={batchName} onChange={(e) => setBatchName(e.target.value)} />
          </div>
          {previewData ? (
            <div className="ingest-preview-summary">
              <div>
                <strong>Preview ready</strong>
                <p className="hint">
                  {previewData.file_count} file{previewData.file_count === 1 ? "" : "s"} detected from{" "}
                  {previewData.outer_filename}.
                </p>
              </div>
              <ul className="ingest-preview-files">
                {previewData.files.map((item) => (
                  <li key={item.inner_name}>
                    {canChooseArchiveMembers ? (
                      <input
                        type="checkbox"
                        checked={selectedFileNameSet.has(item.inner_name)}
                        onChange={(event) => toggleSelectedFile(item.inner_name, event.target.checked)}
                        aria-label={`Import ${item.inner_name}`}
                      />
                    ) : null}
                    <code>{item.inner_name}</code>
                    <span className="ingest-preview-file-meta">
                      <span>
                        {item.format}
                        {item.format_confidence !== undefined
                          ? ` · ${confidenceLabel(item.format_confidence)}`
                          : ""}
                      </span>
                      {item.size !== undefined ? <span>{formatBytes(item.size)}</span> : null}
                    </span>
                  </li>
                ))}
              </ul>
              {canChooseArchiveMembers ? (
                <div className="ingest-preview-actions">
                  <span className="hint">
                    {selectedFileNames.length} of {previewData.files.length} selected.
                  </span>
                  {canMergeSelectedFiles ? (
                    <label className="ingest-option ingest-option--check ingest-option--inline">
                      <input
                        type="checkbox"
                        className="ingest-option__checkbox"
                        checked={mergeArchive}
                        onChange={(e) => setMergeArchive(e.target.checked)}
                      />
                      <span className="ingest-option__check-label">Merge selected files</span>
                      <DocTip text="Concatenate the selected archive members into one ingest with section headers instead of one job per file." />
                    </label>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
          {csvPreviewFiles.length ? (
            <div className="field">
              <div className="label-row">
                <span>CSV column mapping</span>
                <DocTip text="Preview fills the best guess for each CSV header. Set a field to Auto to keep fallback behavior, or Discard to skip that source column entirely." />
              </div>
              <div className="column-map-stack">
                {csvPreviewFiles.map((item) => (
                  <div className="column-map-card" key={item.inner_name}>
                    <div className="column-map-card__head">
                      <div>
                        <strong>{item.inner_name}</strong>
                        <p className="hint">
                          CSV delimiter {item.csv_delimiter || ","}; confidence{" "}
                          {confidenceLabel(item.format_confidence)}
                        </p>
                      </div>
                      <button
                        type="button"
                        className="secondary"
                        disabled={suggestingInnerName === item.inner_name}
                        onClick={() => suggestColumnMap(item)}
                      >
                        {suggestingInnerName === item.inner_name ? "Asking LLM..." : "Suggest with local LLM"}
                      </button>
                    </div>
                    <div className="column-map-card__meta">
                      {(() => {
                        const values = Object.values(columnSelectionsByFile[item.inner_name] ?? {});
                        const mappedCount = values.filter(
                          (value) => value && !isDiscardSelection(value),
                        ).length;
                        const discardedCount = values.filter((value) => isDiscardSelection(value)).length;
                        return (
                          <>
                            <span>{mappedCount} mapped</span>
                            <span>{discardedCount} discarded</span>
                            <span>{Math.max((item.headers ?? []).length - mappedCount - discardedCount, 0)} auto</span>
                          </>
                        );
                      })()}
                    </div>
                    <div className="column-map-table-wrap">
                      <table className="column-map-table">
                        <thead>
                          <tr>
                            <th>Source header</th>
                            <th>Detected</th>
                            <th>Other guesses</th>
                            <th>Preview (first {COLUMN_MAP_SAMPLE_ROW_COUNT} rows)</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(item.headers ?? []).map((header) => {
                            const bestGuess = bestGuessFor(item, header);
                            const guesses = item.column_guesses?.[header] ?? [];
                            const previewValues = (item.sample_rows ?? [])
                              .slice(0, COLUMN_MAP_SAMPLE_ROW_COUNT)
                              .map((row, rowIndex) => ({
                                row: rowIndex + 1,
                                value: row[header] ?? "",
                              }));
                            return (
                              <tr key={`${item.inner_name}:${header}`}>
                                <td>
                                  <code>{header}</code>
                                </td>
                                <td>
                                  {bestGuess ? (
                                    <span>
                                      <code>{bestGuess.field}</code>{" "}
                                      <span className="column-map-confidence">
                                        {confidenceLabel(bestGuess.confidence)}
                                      </span>
                                    </span>
                                  ) : (
                                    <span className="muted">No guess</span>
                                  )}
                                </td>
                                <td>
                                  {guesses.length ? (
                                    <span className="column-map-alternates">
                                      {guesses
                                        .map((guess) => `${guess.field} ${confidenceLabel(guess.confidence)}`)
                                        .join(", ")}
                                    </span>
                                  ) : (
                                    <span className="muted">None</span>
                                  )}
                                </td>
                                <td className="column-map-preview-cell">
                                  {previewValues.length ? (
                                    <ul className="column-map-preview-list">
                                      {previewValues.map((entry) => (
                                        <li key={`${item.inner_name}:${header}:preview:${entry.row}`}>
                                          <span className="column-map-preview-row">{entry.row}.</span>
                                          <span
                                            className={
                                              entry.value ? "column-map-preview-value" : "column-map-preview-empty"
                                            }
                                          >
                                            {entry.value || "—"}
                                          </span>
                                        </li>
                                      ))}
                                    </ul>
                                  ) : (
                                    <span className="muted">No sample rows</span>
                                  )}
                                </td>
                                <td>
                                  <select
                                    aria-label={`Target field for ${header}`}
                                    value={columnSelectionsByFile[item.inner_name]?.[header] ?? ""}
                                    className={
                                      isDiscardSelection(columnSelectionsByFile[item.inner_name]?.[header])
                                        ? "column-map-select--discard"
                                        : undefined
                                    }
                                    onChange={(event) =>
                                      updateColumnSelections({
                                        ...columnSelectionsByFile,
                                        [item.inner_name]: {
                                          ...(columnSelectionsByFile[item.inner_name] ?? {}),
                                          [header]: event.target.value,
                                        },
                                      })
                                    }
                                  >
                                    <option value="">Auto (leave unmapped)</option>
                                    <option value={COLUMN_MAP_DISCARD_VALUE}>Discard column</option>
                                    {canonicalFields.map((field) => (
                                      <option key={field} value={field}>
                                        {field}
                                      </option>
                                    ))}
                                  </select>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {err ? <p className="error">{err}</p> : null}
          {msg ? <p className="hint">{msg}</p> : null}
          <div className="btn-row">
            <span className="btn-with-tip">
              <button type="submit" disabled={primaryBusy || (Boolean(previewData) && !selectedFileNames.length)}>
                {primaryLabel}
              </button>
              <DocTip text="Uploads must be previewed before queueing. Archives spawn one job per selected file unless merge is enabled; follow progress under Jobs and Batches." />
            </span>
          </div>
        </form>
      </section>
    </div>
  );
}
