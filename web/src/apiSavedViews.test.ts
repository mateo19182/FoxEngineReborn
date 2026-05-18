import { beforeEach, describe, expect, it, vi } from "vitest";

import { createSavedView, deleteSavedView, listSavedViews, patchSavedView } from "./api";

type Store = Record<string, string>;

function makeStorage() {
  const store: Store = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      Object.keys(store).forEach((key) => delete store[key]);
    },
  };
}

describe("saved views api helpers", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(globalThis, "localStorage", {
      value: makeStorage(),
      configurable: true,
    });
    localStorage.setItem("fox_jwt", "token");
  });

  it("lists saved views", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify([{ id: "1", name: "A", dsl: "email:*", view: "rows" }]),
    });
    vi.stubGlobal("fetch", fetchMock);

    const out = await listSavedViews();

    expect(fetchMock).toHaveBeenCalledWith("/api/saved-views", expect.any(Object));
    expect(out[0]?.name).toBe("A");
  });

  it("creates, updates, and deletes saved views", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({ id: "2", name: "B", dsl: "phone:*", view: "related" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({ id: "2", name: "B2", dsl: "phone:*", view: "related" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({ status: "ok" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const created = await createSavedView({ name: "B", dsl: "phone:*", view: "related" });
    expect(created.name).toBe("B");

    const updated = await patchSavedView("2", { name: "B2" });
    expect(updated.name).toBe("B2");

    const deleted = await deleteSavedView("2");
    expect(deleted.status).toBe("ok");
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/saved-views/2", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/saved-views/2", expect.any(Object));
  });
});
