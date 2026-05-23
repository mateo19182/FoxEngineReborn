export type JobProgressSnapshot = {
  type: string;
  state: string;
  processed_rows: number;
  total_rows: number | null;
  checkpoint: Record<string, unknown>;
};

export type JobProgressView = {
  mode: "indeterminate" | "determinate";
  value?: number;
  label: string;
};

export function jobProgressView(job: JobProgressSnapshot): JobProgressView {
  if (job.state === "done") {
    const rows = job.processed_rows;
    if (job.type === "export") {
      return {
        mode: "determinate",
        value: 100,
        label: rows > 0 ? `Exported ${rows.toLocaleString()} rows` : "Export done",
      };
    }
    return {
      mode: "determinate",
      value: 100,
      label: rows > 0 ? `${rows.toLocaleString()} rows` : "done",
    };
  }
  if (job.state === "failed") {
    return { mode: "determinate", value: 100, label: "failed" };
  }
  if (job.state === "queued") {
    const label = job.type === "export" ? "Queued" : "queued";
    return { mode: "determinate", value: 0, label };
  }

  if (job.type === "export") {
    return exportJobProgress(job);
  }

  const total = resolveJobTotalRows(job);
  if (total != null && total > 0) {
    const pct = Math.min(100, Math.round((job.processed_rows / total) * 100));
    return {
      mode: "determinate",
      value: pct,
      label: `${job.processed_rows.toLocaleString()} / ${total.toLocaleString()}`,
    };
  }

  if (job.processed_rows > 0) {
    return {
      mode: "indeterminate",
      label: `${job.processed_rows.toLocaleString()} rows`,
    };
  }

  return { mode: "indeterminate", label: "running" };
}

function exportJobProgress(job: JobProgressSnapshot): JobProgressView {
  const phase = exportPhase(job);
  const total = resolveJobTotalRows(job);

  if (phase === "counting") {
    return { mode: "indeterminate", label: "Counting matches…" };
  }

  if (total != null && total > 0 && job.processed_rows > 0) {
    const pct = Math.min(100, Math.round((job.processed_rows / total) * 100));
    return {
      mode: "determinate",
      value: pct,
      label: `${job.processed_rows.toLocaleString()} / ${total.toLocaleString()}`,
    };
  }

  if (phase === "ch_s3_write" || job.checkpoint.export_method === "ch_s3") {
    if (total != null && total > 0) {
      return {
        mode: "indeterminate",
        label: `Writing export (up to ${total.toLocaleString()} rows)…`,
      };
    }
    return { mode: "indeterminate", label: "Writing export…" };
  }

  if (total != null && total > 0) {
    return {
      mode: "determinate",
      value: 0,
      label: `0 / ${total.toLocaleString()}`,
    };
  }

  if (job.processed_rows > 0) {
    return {
      mode: "indeterminate",
      label: `${job.processed_rows.toLocaleString()} rows exported`,
    };
  }

  return { mode: "indeterminate", label: "Exporting…" };
}

function exportPhase(job: JobProgressSnapshot): string | null {
  const phase = job.checkpoint.export_phase;
  return typeof phase === "string" ? phase : null;
}

function resolveJobTotalRows(job: JobProgressSnapshot): number | null {
  if (job.total_rows != null && job.total_rows > 0) return job.total_rows;
  const limit = job.checkpoint.row_limit;
  if (typeof limit === "number" && limit > 0) return limit;
  return null;
}
