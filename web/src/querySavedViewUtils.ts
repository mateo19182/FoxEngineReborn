import type { QueryView, SavedView } from "./api";

export function applySavedViewToQuery(
  savedView: Pick<SavedView, "dsl" | "view">,
): { dsl: string; view: QueryView } {
  return {
    dsl: savedView.dsl,
    view: savedView.view,
  };
}
