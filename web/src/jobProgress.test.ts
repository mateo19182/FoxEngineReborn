import { describe, expect, it } from "vitest";
import { jobProgressView } from "./jobProgress";

describe("jobProgressView", () => {
  it("shows counting phase for exports", () => {
    const view = jobProgressView({
      type: "export",
      state: "running",
      processed_rows: 0,
      total_rows: null,
      checkpoint: { export_phase: "counting" },
    });
    expect(view.mode).toBe("indeterminate");
    expect(view.label).toContain("Counting");
  });

  it("shows determinate progress when export rows are known", () => {
    const view = jobProgressView({
      type: "export",
      state: "running",
      processed_rows: 25_000,
      total_rows: 100_000,
      checkpoint: { export_phase: "streaming", export_method: "stream" },
    });
    expect(view.mode).toBe("determinate");
    expect(view.value).toBe(25);
    expect(view.label).toContain("25,000");
    expect(view.label).toContain("100,000");
  });

  it("shows indeterminate ch_s3 write before row poll", () => {
    const view = jobProgressView({
      type: "export",
      state: "running",
      processed_rows: 0,
      total_rows: 50_000,
      checkpoint: { export_phase: "ch_s3_write", export_method: "ch_s3" },
    });
    expect(view.mode).toBe("indeterminate");
    expect(view.label).toContain("Writing export");
  });

  it("shows done label for completed export", () => {
    const view = jobProgressView({
      type: "export",
      state: "done",
      processed_rows: 1200,
      total_rows: 1200,
      checkpoint: { export_method: "ch_s3" },
    });
    expect(view.value).toBe(100);
    expect(view.label).toContain("Exported");
  });
});
