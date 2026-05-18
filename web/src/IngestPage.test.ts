import { describe, expect, it } from "vitest";

import { getDuplicatePreviewFiles } from "./ingestDuplicateUtils";

describe("getDuplicatePreviewFiles", () => {
  it("returns only selected files with duplicate metadata", () => {
    const files = [
      {
        inner_name: "a.csv",
        format: "csv",
        duplicate_match: {
          source_sha256: "aaa",
          existing_batch_id: "b1",
          existing_filename: "a.csv",
          existing_batch_name: "Old batch",
          ingest_ts: "2026-05-18T08:00:00+00:00",
        },
      },
      { inner_name: "b.csv", format: "csv" },
      {
        inner_name: "c.csv",
        format: "csv",
        duplicate_match: {
          source_sha256: "ccc",
          existing_batch_id: "b2",
          existing_filename: "c.csv",
          existing_batch_name: null,
          ingest_ts: "2026-05-18T09:00:00+00:00",
        },
      },
    ];

    const selected = new Set<string>(["a.csv", "b.csv"]);
    const out = getDuplicatePreviewFiles(files, selected);

    expect(out).toHaveLength(1);
    expect(out[0]?.inner_name).toBe("a.csv");
    expect(out[0]?.duplicate_match?.existing_batch_id).toBe("b1");
  });
});
