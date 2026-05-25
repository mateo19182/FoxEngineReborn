import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { BatchTagForm } from "./BatchTagForm";
import { canIngest } from "./roles";

type Store = "uploads" | "exports";

type BrowseEntry = {
  key: string;
  is_directory: boolean;
  size?: number | null;
  last_modified?: string | null;
};

type StorageFolderContext = {
  kind: "none" | "ingest_batch" | "export_job";
  batch_id?: string | null;
  batch_name?: string | null;
  source_filename?: string | null;
  tag_names?: string[];
  job_id?: string | null;
  job_type?: string | null;
  job_state?: string | null;
  export_dsl?: string | null;
  export_rows?: number | null;
};

type StorageBrowseResponse = {
  store: Store;
  prefix: string;
  entries: BrowseEntry[];
  folder: StorageFolderContext;
};

function clampStoragePrefix(store: Store, dir: string): string {
  const root = store === "uploads" ? "uploads/" : "exports/";
  const p = dir.trim();
  if (!p) {
    return root;
  }
  const need = store === "uploads" ? "uploads/" : "exports/";
  if (!p.startsWith(need.slice(0, -1))) {
    return root;
  }
  if (!p.startsWith(need)) {
    return root;
  }
  return p.endsWith("/") ? p : `${p}/`;
}

function parentPrefix(store: Store, prefix: string): string | null {
  const root = store === "uploads" ? "uploads/" : "exports/";
  if (prefix === root) {
    return null;
  }
  const trimmed = prefix.replace(/\/$/, "");
  const parts = trimmed.split("/").filter(Boolean);
  if (parts.length <= 1) {
    return null;
  }
  parts.pop();
  return `${parts.join("/")}/`;
}

function prefixForBreadcrumbIndex(prefix: string, index: number): string {
  const parts = prefix.replace(/\/$/, "").split("/").filter(Boolean);
  const sub = parts.slice(0, index + 1);
  return `${sub.join("/")}/`;
}

function formatBytes(n: number | null | undefined): string {
  if (n == null || n < 0) {
    return "";
  }
  if (n < 1024) {
    return `${n} B`;
  }
  const kb = n / 1024;
  if (kb < 1024) {
    return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`;
  }
  const mb = kb / 1024;
  if (mb < 1024) {
    return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
  }
  const gb = mb / 1024;
  return `${gb < 10 ? gb.toFixed(1) : Math.round(gb)} GB`;
}

export function StoragePage() {
  const [store, setStore] = useState<Store>("uploads");
  const [prefix, setPrefix] = useState("uploads/");
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [folder, setFolder] = useState<StorageFolderContext>({ kind: "none" });
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(() => new Set());
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [operator, setOperator] = useState(false);

  useEffect(() => {
    void api<{ roles: string[] }>("/auth/me")
      .then((m) => setOperator(canIngest(m.roles)))
      .catch(() => setOperator(false));
  }, []);

  const load = useCallback(async (nextStore: Store, nextPrefix: string) => {
    const p = clampStoragePrefix(nextStore, nextPrefix);
    setLoading(true);
    setErr(null);
    setSelectedFiles(new Set());
    try {
      const q = encodeURIComponent(p);
      const data = await api<StorageBrowseResponse>(
        `/storage/browse?store=${encodeURIComponent(nextStore)}&prefix=${q}`,
      );
      setStore(data.store);
      setPrefix(data.prefix);
      setEntries(data.entries);
      setFolder(data.folder ?? { kind: "none" });
    } catch (e) {
      setErr(String(e));
      setEntries([]);
      setFolder({ kind: "none" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = window.setTimeout(() => {
      void load("uploads", "uploads/");
    }, 0);
    return () => window.clearTimeout(t);
  }, [load]);

  const switchStore = (next: Store) => {
    void load(next, next === "uploads" ? "uploads/" : "exports/");
  };

  const enterDirectory = (name: string) => {
    void load(store, `${prefix}${name}/`);
  };

  const goToPrefix = (nextPrefix: string) => {
    void load(store, nextPrefix);
  };

  const up = () => {
    const par = parentPrefix(store, prefix);
    if (par) {
      void load(store, par);
    }
  };

  const crumbs = prefix.replace(/\/$/, "").split("/").filter(Boolean);

  const fileEntries = entries.filter((e) => !e.is_directory);
  const allFilesSelected =
    fileEntries.length > 0 && fileEntries.every((e) => selectedFiles.has(e.key));

  const toggleFile = (key: string) => {
    setSelectedFiles((prev) => {
      const n = new Set(prev);
      if (n.has(key)) {
        n.delete(key);
      } else {
        n.add(key);
      }
      return n;
    });
  };

  const toggleSelectAllFiles = () => {
    if (allFilesSelected) {
      setSelectedFiles(new Set());
    } else {
      setSelectedFiles(new Set(fileEntries.map((e) => e.key)));
    }
  };

  const downloadSelected = async () => {
    if (!selectedFiles.size) {
      return;
    }
    setDownloadBusy(true);
    setErr(null);
    try {
      for (const name of selectedFiles) {
        const fullKey = `${prefix}${name}`;
        const q = encodeURIComponent(fullKey);
        const { url } = await api<{ url: string }>(
          `/storage/presign?store=${encodeURIComponent(store)}&key=${q}`,
        );
        window.open(url, "_blank", "noopener,noreferrer");
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setDownloadBusy(false);
    }
  };

  return (
    <div>
      <header className="page-head">
        <div>
          <h1>Storage</h1>
          <p className="lead">
            Ingest files under <code>uploads/</code>, export results under <code>exports/</code>. Download uses a
            short-lived signed URL.
          </p>
          <div className="storage-store-switch" role="tablist" aria-label="Bucket">
            <button
              type="button"
              role="tab"
              aria-selected={store === "uploads"}
              className={store === "uploads" ? "storage-store-switch__active" : undefined}
              onClick={() => switchStore("uploads")}
            >
              Uploads
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={store === "exports"}
              className={store === "exports" ? "storage-store-switch__active" : undefined}
              onClick={() => switchStore("exports")}
            >
              Exports
            </button>
          </div>
        </div>
      </header>

      {err ? <p className="error">{err}</p> : null}
      {loading ? <p className="muted">Loading listing…</p> : null}

      {folder.kind === "ingest_batch" ? (
        <section className="panel" style={{ marginBottom: "1rem" }}>
          <div className="panel__head">
            <h2>Batch</h2>
          </div>
          {folder.batch_name ? <p style={{ marginTop: 0 }}>{folder.batch_name}</p> : null}
          {folder.source_filename ? (
            <p className="hint" style={{ marginTop: "0.35rem" }}>
              Source file: {folder.source_filename}
            </p>
          ) : null}
          {folder.batch_id ? (
            <p className="hint" style={{ fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>
              {folder.batch_id}
            </p>
          ) : null}
          <p className="hint" style={{ marginBottom: "0.35rem" }}>
            Tags on rows in this batch
          </p>
          {folder.tag_names && folder.tag_names.length ? (
            <ul className="tag-chips">
              {folder.tag_names.map((t) => (
                <li key={t} className="tag-chip-item">
                  <span className="tag-chip__label">{t}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No tags on ingested rows in this batch yet.</p>
          )}
          {operator && folder.batch_id ? (
            <div style={{ marginTop: "1rem" }}>
              <BatchTagForm
                batchId={folder.batch_id}
                onQueued={() => {
                  void load(store, prefix).catch((e) => setErr(String(e)));
                }}
              />
            </div>
          ) : null}
        </section>
      ) : null}

      {folder.kind === "export_job" ? (
        <section className="panel" style={{ marginBottom: "1rem" }}>
          <div className="panel__head">
            <h2>Export job</h2>
          </div>
          {folder.job_id ? (
            <p className="hint" style={{ fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>
              Job {folder.job_id}
            </p>
          ) : null}
          {folder.job_type ? (
            <p className="hint">
              Type {folder.job_type}
              {folder.job_state ? ` · ${folder.job_state}` : ""}
            </p>
          ) : null}
          {folder.export_rows != null ? <p className="hint">Rows written: {folder.export_rows}</p> : null}
          {folder.export_dsl ? <pre className="code-block" style={{ maxHeight: "10rem", overflow: "auto" }}>{folder.export_dsl}</pre> : null}
        </section>
      ) : null}

      <section className="panel">
        <div className="panel__head" style={{ alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
          <h2 style={{ margin: 0 }}>Objects</h2>
          <div className="btn-row" style={{ marginLeft: "auto" }}>
            {parentPrefix(store, prefix) ? (
              <button type="button" className="secondary" onClick={up}>
                Up
              </button>
            ) : null}
            <button
              type="button"
              disabled={!selectedFiles.size || downloadBusy}
              onClick={() => {
                void downloadSelected();
              }}
            >
              {downloadBusy ? "Preparing…" : "Download selected"}
            </button>
          </div>
        </div>
        <nav className="hint" style={{ marginBottom: "0.75rem", lineHeight: 1.6 }}>
          {crumbs.map((seg, i) => (
            <span key={`${i}-${seg}`}>
              {i > 0 ? " / " : null}
              <button
                type="button"
                className="secondary"
                style={{ display: "inline", padding: "0.15rem 0.4rem", fontSize: "0.85rem" }}
                onClick={() => goToPrefix(prefixForBreadcrumbIndex(prefix, i))}
              >
                {seg}
              </button>
            </span>
          ))}
        </nav>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th style={{ width: "2.5rem" }}>
                  <input
                    type="checkbox"
                    checked={allFilesSelected}
                    disabled={!fileEntries.length}
                    onChange={toggleSelectAllFiles}
                    title="Select all files in this folder"
                  />
                </th>
                <th>Name</th>
                <th>Type</th>
                <th className="muted" style={{ textAlign: "right" }}>
                  Size
                </th>
                <th className="muted" style={{ textAlign: "right" }}>
                  Modified
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) =>
                e.is_directory ? (
                  <tr key={`d-${e.key}`}>
                    <td />
                    <td>
                      <button
                        type="button"
                        className="secondary"
                        style={{ fontWeight: 600 }}
                        onClick={() => enterDirectory(e.key)}
                      >
                        {e.key}/
                      </button>
                    </td>
                    <td className="muted">Folder</td>
                    <td />
                    <td />
                  </tr>
                ) : (
                  <tr key={`f-${e.key}`}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedFiles.has(e.key)}
                        onChange={() => toggleFile(e.key)}
                      />
                    </td>
                    <td>{e.key}</td>
                    <td className="muted">File</td>
                    <td style={{ textAlign: "right" }}>{formatBytes(e.size ?? undefined)}</td>
                    <td className="muted" style={{ textAlign: "right", fontSize: "0.85rem" }}>
                      {e.last_modified
                        ? new Date(e.last_modified).toLocaleString(undefined, {
                            dateStyle: "short",
                            timeStyle: "short",
                          })
                        : ""}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
        {!entries.length && !loading ? <p className="muted">This folder is empty.</p> : null}
      </section>
    </div>
  );
}
