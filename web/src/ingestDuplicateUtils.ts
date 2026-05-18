type DuplicateCandidate = {
  inner_name: string;
  duplicate_match?: unknown;
};

export function getDuplicatePreviewFiles<T extends DuplicateCandidate>(
  files: T[] | undefined,
  selectedFileNameSet: Set<string>,
): T[] {
  return (files ?? []).filter(
    (item) => selectedFileNameSet.has(item.inner_name) && Boolean(item.duplicate_match),
  );
}
