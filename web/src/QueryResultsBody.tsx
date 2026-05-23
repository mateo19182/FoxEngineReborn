import type { DisplayColumn, ResultsLayout, TagLookup } from "./queryResultsDisplay";
import {
  extrasSummary,
  formatDisplayValue,
  relatedMatchLabel,
  resultCardSubline,
  resultCardTitle,
  tagNamesForRow,
} from "./queryResultsDisplay";

type Props = {
  rows: Record<string, unknown>[];
  columns: DisplayColumn[];
  layout: ResultsLayout;
  tagLookup: TagLookup;
  relatedView: boolean;
  activeIndex: number | null;
  onSelectRow: (index: number) => void;
  rowKey: (row: Record<string, unknown>) => string;
  rowClassName: (row: Record<string, unknown>, active: boolean) => string | undefined;
};

export function QueryResultsBody({
  rows,
  columns,
  layout,
  tagLookup,
  relatedView,
  activeIndex,
  onSelectRow,
  rowKey,
  rowClassName,
}: Props) {
  if (layout === "cards") {
    return (
      <div className="results-cards" role="list">
        {rows.map((row, index) => (
          <ResultCard
            key={rowKey(row)}
            row={row}
            index={index}
            columns={columns}
            tagLookup={tagLookup}
            relatedView={relatedView}
            active={activeIndex === index}
            className={rowClassName(row, activeIndex === index)}
            onSelect={() => onSelectRow(index)}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="results-table-wrap">
      <table className="results-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.id}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={rowKey(row)}
              className={rowClassName(row, activeIndex === index)}
              tabIndex={0}
              onClick={() => onSelectRow(index)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelectRow(index);
                }
              }}
            >
              {columns.map((col) => (
                <td key={col.id}>
                  <ResultCell row={row} column={col} tagLookup={tagLookup} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultCell({
  row,
  column,
  tagLookup,
}: {
  row: Record<string, unknown>;
  column: DisplayColumn;
  tagLookup: TagLookup;
}) {
  const value = column.getValue(row);
  if (column.kind === "tags") {
    const names = tagNamesForRow(row, tagLookup);
    if (names.length === 0) return null;
    return (
      <span className="result-chips">
        {names.map((name) => (
          <span key={name} className="result-chip">
            {name}
          </span>
        ))}
      </span>
    );
  }
  if (column.kind === "extras") {
    const summary = extrasSummary(value);
    if (summary.count === 0) return null;
    return (
      <span className="result-extras" title={summary.preview}>
        {summary.count} field{summary.count === 1 ? "" : "s"}
      </span>
    );
  }
  if (column.kind === "related_match") {
    const label = relatedMatchLabel(value);
    if (!label) return null;
    return <span className="result-match-label">{label}</span>;
  }
  const text = formatDisplayValue(value);
  if (!text) return null;
  return <span className="result-cell-text">{text}</span>;
}

function ResultCard({
  row,
  index,
  columns,
  tagLookup,
  relatedView,
  active,
  className,
  onSelect,
}: {
  row: Record<string, unknown>;
  index: number;
  columns: DisplayColumn[];
  tagLookup: TagLookup;
  relatedView: boolean;
  active: boolean;
  className: string | undefined;
  onSelect: () => void;
}) {
  const title = resultCardTitle(row);
  const subline = resultCardSubline(row, columns, title);
  const tagNames = tagNamesForRow(row, tagLookup);
  const extras = extrasSummary(columns.find((c) => c.id === "extras")?.getValue(row));
  const matchCol = columns.find((c) => c.id === "_related_is_match");
  const groupCol = columns.find((c) => c.id === "_related_group");
  const matchLabel = matchCol ? relatedMatchLabel(matchCol.getValue(row)) : "";
  const groupLabel =
    groupCol && formatDisplayValue(groupCol.getValue(row))
      ? `Group ${formatDisplayValue(groupCol.getValue(row))}`
      : "";

  const classes = ["results-card", className, active ? "results-card--active" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <article
      className={classes}
      role="listitem"
      tabIndex={0}
      aria-label={`Result ${index + 1}, ${title}`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="results-card__head">
        <h3 className="results-card__title">{title}</h3>
        {relatedView && (groupLabel || matchLabel) ? (
          <span className="results-card__badges">
            {groupLabel ? <span className="result-chip result-chip--muted">{groupLabel}</span> : null}
            {matchLabel ? <span className="result-chip result-chip--muted">{matchLabel}</span> : null}
          </span>
        ) : null}
      </div>
      {subline ? <p className="results-card__subline">{subline}</p> : null}
      {tagNames.length > 0 || extras.count > 0 ? (
        <div className="results-card__footer">
          {tagNames.length > 0 ? (
            <span className="result-chips">
              {tagNames.map((name) => (
                <span key={name} className="result-chip">
                  {name}
                </span>
              ))}
            </span>
          ) : null}
          {extras.count > 0 ? (
            <span className="result-extras" title={extras.preview}>
              {extras.count} extra{extras.count === 1 ? "" : "s"}
            </span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
