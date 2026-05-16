import { useCallback, useEffect, useState } from "react";
import { S3FileBrowser, type S3FileOrDirectory } from "@sqlrooms/s3-browser";
import { Button } from "@sqlrooms/ui";
import { api, getToken } from "./api";
import { canIngest } from "./roles";

type UploadBrowseEntry = {
  key: string;
  is_directory: boolean;
  size?: number | null;
  content_type?: string | null;
  last_modified?: string | null;
};

type UploadBrowseResponse = {
  prefix: string;
  entries: UploadBrowseEntry[];
};

function clampUploadsPrefix(dir: string): string {
  if (!dir.startsWith("uploads/")) {
    return "uploads/";
  }
  return dir;
}

function mapEntries(entries: UploadBrowseEntry[]): S3FileOrDirectory[] {
  return entries.map((e) => {
    if (e.is_directory) {
      return { key: e.key, isDirectory: true as const };
    }
    return {
      key: e.key,
      isDirectory: false as const,
      size: e.size ?? undefined,
      contentType: e.content_type ?? undefined,
      lastModified: e.last_modified ? new Date(e.last_modified) : undefined,
    };
  });
}

export function UploadsBrowserApp() {
  const [allowed, setAllowed] = useState<boolean | null>(() => (getToken() ? null : false));
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [files, setFiles] = useState<S3FileOrDirectory[]>([]);
  const [selectedDirectory, setSelectedDirectory] = useState("uploads/");
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [downloadBusy, setDownloadBusy] = useState(false);

  useEffect(() => {
    if (allowed !== null) {
      return;
    }
    let cancelled = false;
    (async () => {
      await undefined;
      const token = getToken();
      if (!token) {
        if (!cancelled) {
          setAllowed(false);
        }
        return;
      }
      try {
        const m = await api<{ roles: string[] }>("/auth/me");
        if (cancelled) {
          return;
        }
        setAllowed(canIngest(m.roles));
      } catch {
        if (!cancelled) {
          setAllowed(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [allowed]);

  const loadPrefix = useCallback(async (prefix: string) => {
    const p = clampUploadsPrefix(prefix);
    await undefined;
    setLoading(true);
    setErr(null);
    try {
      const q = encodeURIComponent(p);
      const data = await api<UploadBrowseResponse>(`/uploads/browse?prefix=${q}`);
      setFiles(mapEntries(data.entries));
      setSelectedDirectory(data.prefix);
    } catch (e) {
      setErr(String(e));
      setFiles([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (allowed !== true) {
      return;
    }
    let cancelled = false;
    (async () => {
      await undefined;
      await loadPrefix("uploads/");
      if (cancelled) {
        return;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [allowed, loadPrefix]);

  const onChangeSelectedDirectory = useCallback(
    (dir: string) => {
      const next = clampUploadsPrefix(dir);
      void loadPrefix(next);
    },
    [loadPrefix],
  );

  const downloadSelected = useCallback(async () => {
    if (!selectedFiles.length) {
      return;
    }
    setDownloadBusy(true);
    setErr(null);
    try {
      for (const name of selectedFiles) {
        const fullKey = `${selectedDirectory}${name}`;
        const q = encodeURIComponent(fullKey);
        const { url } = await api<{ url: string }>(`/uploads/presign?key=${q}`);
        window.open(url, "_blank", "noopener,noreferrer");
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setDownloadBusy(false);
    }
  }, [selectedDirectory, selectedFiles]);

  if (allowed === null) {
    return (
      <div className="text-muted-foreground flex min-h-screen items-center justify-center p-6 text-sm">
        Loading…
      </div>
    );
  }

  if (!allowed) {
    return (
      <div className="bg-background text-foreground flex min-h-screen flex-col gap-4 p-8">
        <h1 className="text-lg font-semibold">Upload storage</h1>
        <p className="text-muted-foreground text-sm">
          Sign in with an operator, manager, or admin account in the main app, then open this page again.
        </p>
        <p>
          <a className="text-primary text-sm underline" href="/login">
            Go to login
          </a>
        </p>
      </div>
    );
  }

  return (
    <div className="bg-background text-foreground flex min-h-screen flex-col gap-3 p-4 md:p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Upload storage</h1>
          <p className="text-muted-foreground text-xs">
            Ingested files under the <code className="text-foreground">uploads/</code> prefix. Download opens a
            time-limited link in a new tab.
          </p>
        </div>
        <a className="text-primary text-sm underline" href="/ingest">
          Back to ingest
        </a>
      </header>
      {err ? <p className="text-destructive text-sm">{err}</p> : null}
      {loading ? (
        <p className="text-muted-foreground text-sm">Loading listing…</p>
      ) : null}
      <div className="min-h-[50vh] w-full min-w-0 flex-1">
        <S3FileBrowser
          files={files}
          selectedFiles={selectedFiles}
          selectedDirectory={selectedDirectory}
          onCanConfirmChange={() => {}}
          onChangeSelectedDirectory={onChangeSelectedDirectory}
          onChangeSelectedFiles={setSelectedFiles}
          renderFileActions={() => (
            <Button type="button" size="sm" disabled={!selectedFiles.length || downloadBusy} onClick={downloadSelected}>
              {downloadBusy ? "Preparing…" : "Download selected"}
            </Button>
          )}
        />
      </div>
    </div>
  );
}
